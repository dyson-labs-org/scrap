//! Payment tracking and management

use std::collections::HashMap;
use std::sync::RwLock;
use serde::{Serialize, Deserialize};

/// Payment status
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PaymentStatus {
    /// Payment is pending (HTLC in flight)
    Pending,
    /// Payment succeeded (preimage received)
    Succeeded,
    /// Payment failed
    Failed,
    /// Payment expired (HTLC timed out)
    Expired,
}

/// Information about a payment
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PaymentInfo {
    /// Payment hash (32 bytes hex)
    pub payment_hash: String,
    /// Payment preimage (32 bytes hex, if known)
    pub preimage: Option<String>,
    /// Amount in millisatoshis
    pub amount_msat: u64,
    /// Payment status
    pub status: PaymentStatus,
    /// Associated task JTI (for SCAP binding)
    pub task_jti: Option<String>,
    /// Creation timestamp
    pub created_at: u64,
    /// Last update timestamp
    pub updated_at: u64,
    /// Number of routing attempts
    pub attempts: u32,
    /// Error message if failed
    pub error: Option<String>,
}

/// Payment tracker
pub struct PaymentTracker {
    /// Outbound payments (we initiated)
    outbound: RwLock<HashMap<String, PaymentInfo>>,
    /// Inbound payments (we received)
    inbound: RwLock<HashMap<String, PaymentInfo>>,
    /// Timestamp provider
    get_timestamp: Box<dyn Fn() -> u64 + Send + Sync>,
}

impl PaymentTracker {
    /// Create a new payment tracker
    pub fn new() -> Self {
        Self::with_timestamp(|| {
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0)
        })
    }

    /// Create with custom timestamp provider
    pub fn with_timestamp<F: Fn() -> u64 + Send + Sync + 'static>(get_timestamp: F) -> Self {
        Self {
            outbound: RwLock::new(HashMap::new()),
            inbound: RwLock::new(HashMap::new()),
            get_timestamp: Box::new(get_timestamp),
        }
    }

    /// Track a new outbound payment
    pub fn track_outbound(&self, payment_hash: String, amount_msat: u64, task_jti: Option<String>) {
        let now = (self.get_timestamp)();
        let info = PaymentInfo {
            payment_hash: payment_hash.clone(),
            preimage: None,
            amount_msat,
            status: PaymentStatus::Pending,
            task_jti,
            created_at: now,
            updated_at: now,
            attempts: 1,
            error: None,
        };
        self.outbound.write().unwrap().insert(payment_hash, info);
    }

    /// Track a new inbound payment (invoice created)
    pub fn track_inbound(&self, payment_hash: String, amount_msat: u64, task_jti: Option<String>) {
        let now = (self.get_timestamp)();
        let info = PaymentInfo {
            payment_hash: payment_hash.clone(),
            preimage: None,
            amount_msat,
            status: PaymentStatus::Pending,
            task_jti,
            created_at: now,
            updated_at: now,
            attempts: 0,
            error: None,
        };
        self.inbound.write().unwrap().insert(payment_hash, info);
    }

    /// Update outbound payment status
    pub fn update_outbound(&self, payment_hash: &str, status: PaymentStatus, preimage: Option<String>, error: Option<String>) {
        let now = (self.get_timestamp)();
        if let Some(info) = self.outbound.write().unwrap().get_mut(payment_hash) {
            info.status = status;
            info.preimage = preimage;
            info.error = error;
            info.updated_at = now;
        }
    }

    /// Update inbound payment status
    pub fn update_inbound(&self, payment_hash: &str, status: PaymentStatus, preimage: Option<String>) {
        let now = (self.get_timestamp)();
        if let Some(info) = self.inbound.write().unwrap().get_mut(payment_hash) {
            info.status = status;
            info.preimage = preimage;
            info.updated_at = now;
        }
    }

    /// Increment retry count for outbound payment
    pub fn increment_attempts(&self, payment_hash: &str) {
        if let Some(info) = self.outbound.write().unwrap().get_mut(payment_hash) {
            info.attempts += 1;
        }
    }

    /// Get outbound payment info
    pub fn get_outbound(&self, payment_hash: &str) -> Option<PaymentInfo> {
        self.outbound.read().unwrap().get(payment_hash).cloned()
    }

    /// Get inbound payment info
    pub fn get_inbound(&self, payment_hash: &str) -> Option<PaymentInfo> {
        self.inbound.read().unwrap().get(payment_hash).cloned()
    }

    /// Get all pending outbound payments
    pub fn pending_outbound(&self) -> Vec<PaymentInfo> {
        self.outbound.read().unwrap()
            .values()
            .filter(|p| p.status == PaymentStatus::Pending)
            .cloned()
            .collect()
    }

    /// Get all pending inbound payments
    pub fn pending_inbound(&self) -> Vec<PaymentInfo> {
        self.inbound.read().unwrap()
            .values()
            .filter(|p| p.status == PaymentStatus::Pending)
            .cloned()
            .collect()
    }

    /// Get payment by task JTI
    pub fn get_by_task(&self, task_jti: &str) -> Option<PaymentInfo> {
        // Check outbound first
        if let Some(info) = self.outbound.read().unwrap()
            .values()
            .find(|p| p.task_jti.as_deref() == Some(task_jti))
        {
            return Some(info.clone());
        }

        // Check inbound
        self.inbound.read().unwrap()
            .values()
            .find(|p| p.task_jti.as_deref() == Some(task_jti))
            .cloned()
    }

    /// Clean up old completed payments
    pub fn cleanup(&self, max_age_secs: u64) {
        let now = (self.get_timestamp)();
        let cutoff = now.saturating_sub(max_age_secs);

        self.outbound.write().unwrap().retain(|_, p| {
            p.status == PaymentStatus::Pending || p.updated_at > cutoff
        });

        self.inbound.write().unwrap().retain(|_, p| {
            p.status == PaymentStatus::Pending || p.updated_at > cutoff
        });
    }
}

impl Default for PaymentTracker {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_track_outbound() {
        let tracker = PaymentTracker::new();
        tracker.track_outbound("hash1".to_string(), 1000, Some("task-001".to_string()));

        let info = tracker.get_outbound("hash1").unwrap();
        assert_eq!(info.amount_msat, 1000);
        assert_eq!(info.status, PaymentStatus::Pending);
        assert_eq!(info.task_jti, Some("task-001".to_string()));
    }

    #[test]
    fn test_update_status() {
        let tracker = PaymentTracker::new();
        tracker.track_outbound("hash1".to_string(), 1000, None);

        tracker.update_outbound(
            "hash1",
            PaymentStatus::Succeeded,
            Some("preimage123".to_string()),
            None
        );

        let info = tracker.get_outbound("hash1").unwrap();
        assert_eq!(info.status, PaymentStatus::Succeeded);
        assert_eq!(info.preimage, Some("preimage123".to_string()));
    }

    #[test]
    fn test_get_by_task() {
        let tracker = PaymentTracker::new();
        tracker.track_outbound("hash1".to_string(), 1000, Some("task-001".to_string()));
        tracker.track_inbound("hash2".to_string(), 2000, Some("task-002".to_string()));

        let info1 = tracker.get_by_task("task-001").unwrap();
        assert_eq!(info1.payment_hash, "hash1");

        let info2 = tracker.get_by_task("task-002").unwrap();
        assert_eq!(info2.payment_hash, "hash2");
    }

    #[test]
    fn test_pending_payments() {
        let tracker = PaymentTracker::new();
        tracker.track_outbound("hash1".to_string(), 1000, None);
        tracker.track_outbound("hash2".to_string(), 2000, None);
        tracker.update_outbound("hash1", PaymentStatus::Succeeded, None, None);

        let pending = tracker.pending_outbound();
        assert_eq!(pending.len(), 1);
        assert_eq!(pending[0].payment_hash, "hash2");
    }
}

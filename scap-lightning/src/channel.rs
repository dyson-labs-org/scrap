//! Satellite channel management
//!
//! Wraps LDK's ChannelManager with satellite-specific functionality.

use crate::config::SatelliteConfig;
use crate::payment::{PaymentTracker, PaymentStatus};
use crate::binding::{BindingManager, BindingStatus};
use serde::{Serialize, Deserialize};

/// Satellite channel manager
///
/// This wraps LDK components with satellite-specific functionality:
/// - Task-payment binding
/// - Ground uplink coordination
/// - Timeout handling for orbital constraints
pub struct SatelliteChannelManager {
    /// Configuration
    config: SatelliteConfig,
    /// Payment tracker
    payments: PaymentTracker,
    /// Task-payment bindings
    bindings: BindingManager,
    /// Channel states (simplified for this implementation)
    channels: std::sync::RwLock<Vec<ChannelInfo>>,
}

impl SatelliteChannelManager {
    /// Create a new satellite channel manager
    pub fn new(config: SatelliteConfig) -> Self {
        Self {
            config,
            payments: PaymentTracker::new(),
            bindings: BindingManager::new(),
            channels: std::sync::RwLock::new(Vec::new()),
        }
    }

    /// Get the configuration
    pub fn config(&self) -> &SatelliteConfig {
        &self.config
    }

    /// Get payment tracker
    pub fn payments(&self) -> &PaymentTracker {
        &self.payments
    }

    /// Get binding manager
    pub fn bindings(&self) -> &BindingManager {
        &self.bindings
    }

    /// Register a channel
    pub fn register_channel(&self, channel: ChannelInfo) {
        self.channels.write().unwrap().push(channel);
    }

    /// Get channel by ID
    pub fn get_channel(&self, channel_id: &str) -> Option<ChannelInfo> {
        self.channels.read().unwrap()
            .iter()
            .find(|c| c.channel_id == channel_id)
            .cloned()
    }

    /// Get all channels
    pub fn list_channels(&self) -> Vec<ChannelInfo> {
        self.channels.read().unwrap().clone()
    }

    /// Get total outbound capacity (msat)
    pub fn outbound_capacity_msat(&self) -> u64 {
        self.channels.read().unwrap()
            .iter()
            .filter(|c| c.is_usable)
            .map(|c| c.outbound_capacity_msat)
            .sum()
    }

    /// Get total inbound capacity (msat)
    pub fn inbound_capacity_msat(&self) -> u64 {
        self.channels.read().unwrap()
            .iter()
            .filter(|c| c.is_usable)
            .map(|c| c.inbound_capacity_msat)
            .sum()
    }

    /// Process a payment received event
    pub fn on_payment_received(&self, payment_hash: &str, amount_msat: u64) {
        // Update payment tracker
        self.payments.track_inbound(payment_hash.to_string(), amount_msat, None);

        // Check if this is linked to a task binding
        if let Some(binding) = self.bindings.get_by_payment_hash(payment_hash) {
            log::info!(
                "Payment {} received for task {}",
                payment_hash, binding.task_jti
            );
        }
    }

    /// Process a payment sent event
    pub fn on_payment_sent(&self, payment_hash: &str, preimage: &str) {
        self.payments.update_outbound(
            payment_hash,
            PaymentStatus::Succeeded,
            Some(preimage.to_string()),
            None,
        );

        // Update binding status
        if let Some(binding) = self.bindings.get_by_payment_hash(payment_hash) {
            self.bindings.update_status(&binding.task_jti, BindingStatus::Settled);
            log::info!(
                "Payment {} settled for task {}",
                payment_hash, binding.task_jti
            );
        }
    }

    /// Process a payment failed event
    pub fn on_payment_failed(&self, payment_hash: &str, error: &str) {
        self.payments.update_outbound(
            payment_hash,
            PaymentStatus::Failed,
            None,
            Some(error.to_string()),
        );

        // Update binding status
        if let Some(binding) = self.bindings.get_by_payment_hash(payment_hash) {
            self.bindings.update_status(&binding.task_jti, BindingStatus::Failed);
            log::warn!(
                "Payment {} failed for task {}: {}",
                payment_hash, binding.task_jti, error
            );
        }
    }

    /// Get status summary
    pub fn status(&self) -> ManagerStatus {
        let channels = self.channels.read().unwrap();
        ManagerStatus {
            satellite_id: self.config.satellite_id.clone(),
            num_channels: channels.len(),
            num_usable_channels: channels.iter().filter(|c| c.is_usable).count(),
            total_outbound_msat: self.outbound_capacity_msat(),
            total_inbound_msat: self.inbound_capacity_msat(),
            pending_outbound_payments: self.payments.pending_outbound().len(),
            pending_inbound_payments: self.payments.pending_inbound().len(),
            pending_bindings: self.bindings.get_pending().len(),
        }
    }
}

/// Channel information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChannelInfo {
    /// Channel ID (funding txid:output_index)
    pub channel_id: String,
    /// Remote peer's node ID (pubkey hex)
    pub peer_id: String,
    /// Channel capacity in satoshis
    pub capacity_sat: u64,
    /// Our balance in millisatoshis
    pub local_balance_msat: u64,
    /// Their balance in millisatoshis
    pub remote_balance_msat: u64,
    /// Outbound capacity available (msat)
    pub outbound_capacity_msat: u64,
    /// Inbound capacity available (msat)
    pub inbound_capacity_msat: u64,
    /// Number of pending HTLCs
    pub pending_htlcs: u32,
    /// Is channel usable for payments?
    pub is_usable: bool,
    /// Is channel public?
    pub is_public: bool,
    /// Confirmation count
    pub confirmations: u32,
}

/// Manager status summary
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ManagerStatus {
    pub satellite_id: String,
    pub num_channels: usize,
    pub num_usable_channels: usize,
    pub total_outbound_msat: u64,
    pub total_inbound_msat: u64,
    pub pending_outbound_payments: usize,
    pub pending_inbound_payments: usize,
    pub pending_bindings: usize,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config() -> SatelliteConfig {
        SatelliteConfig {
            satellite_id: "TEST-SAT-001".to_string(),
            ..Default::default()
        }
    }

    fn test_channel() -> ChannelInfo {
        ChannelInfo {
            channel_id: "abc123:0".to_string(),
            peer_id: "02abc...".to_string(),
            capacity_sat: 1_000_000,
            local_balance_msat: 500_000_000,
            remote_balance_msat: 500_000_000,
            outbound_capacity_msat: 450_000_000,
            inbound_capacity_msat: 450_000_000,
            pending_htlcs: 0,
            is_usable: true,
            is_public: false,
            confirmations: 6,
        }
    }

    #[test]
    fn test_create_manager() {
        let config = test_config();
        let manager = SatelliteChannelManager::new(config);

        assert_eq!(manager.config().satellite_id, "TEST-SAT-001");
        assert_eq!(manager.list_channels().len(), 0);
    }

    #[test]
    fn test_register_channel() {
        let manager = SatelliteChannelManager::new(test_config());
        let channel = test_channel();

        manager.register_channel(channel.clone());

        assert_eq!(manager.list_channels().len(), 1);
        assert_eq!(manager.outbound_capacity_msat(), 450_000_000);
    }

    #[test]
    fn test_status() {
        let manager = SatelliteChannelManager::new(test_config());
        manager.register_channel(test_channel());

        let status = manager.status();
        assert_eq!(status.num_channels, 1);
        assert_eq!(status.num_usable_channels, 1);
        assert_eq!(status.total_outbound_msat, 450_000_000);
    }

    #[test]
    fn test_payment_events() {
        let manager = SatelliteChannelManager::new(test_config());

        manager.on_payment_received("hash123", 1_000_000);
        assert_eq!(manager.payments().pending_inbound().len(), 1);

        manager.on_payment_sent("hash456", "preimage123");
        // Would need to track outbound first for this to update
    }
}

//! Transaction broadcaster for satellite environment
//!
//! Satellites cannot broadcast transactions directly to the Bitcoin network.
//! Instead, transactions are queued and broadcast via ground station uplink.

use lightning::chain::chaininterface::BroadcasterInterface;
use bitcoin::Transaction;
use std::sync::{Arc, Mutex};
use std::collections::VecDeque;
use serde::{Serialize, Deserialize};

/// Queued transaction with metadata
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueuedTransaction {
    /// Serialized transaction (hex)
    pub tx_hex: String,
    /// Transaction ID
    pub txid: String,
    /// Priority level
    pub priority: TxPriority,
    /// Timestamp when queued (Unix epoch)
    pub queued_at: u64,
    /// Number of broadcast attempts
    pub attempts: u32,
}

/// Transaction priority for ground uplink ordering
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum TxPriority {
    /// Justice transactions (highest priority)
    Justice = 0,
    /// Force close sweeps
    ForceClosure = 1,
    /// Commitment transactions
    Commitment = 2,
    /// Channel close
    ChannelClose = 3,
    /// Channel open (lowest priority)
    ChannelOpen = 4,
}

/// Transaction broadcaster that queues for ground uplink
pub struct SatelliteBroadcaster {
    /// Queue of transactions to broadcast
    queue: Mutex<VecDeque<QueuedTransaction>>,
    /// Maximum queue size
    max_queue_size: usize,
    /// Current timestamp provider
    get_timestamp: Box<dyn Fn() -> u64 + Send + Sync>,
}

impl SatelliteBroadcaster {
    /// Create a new broadcaster with default settings
    pub fn new() -> Self {
        Self::with_timestamp(|| {
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0)
        })
    }

    /// Create a broadcaster with custom timestamp provider
    pub fn with_timestamp<F: Fn() -> u64 + Send + Sync + 'static>(get_timestamp: F) -> Self {
        Self {
            queue: Mutex::new(VecDeque::new()),
            max_queue_size: 100,
            get_timestamp: Box::new(get_timestamp),
        }
    }

    /// Create an Arc-wrapped broadcaster
    pub fn arc() -> Arc<Self> {
        Arc::new(Self::new())
    }

    /// Get all queued transactions (sorted by priority)
    pub fn get_queue(&self) -> Vec<QueuedTransaction> {
        let queue = self.queue.lock().unwrap();
        let mut txs: Vec<_> = queue.iter().cloned().collect();
        txs.sort_by_key(|tx| tx.priority);
        txs
    }

    /// Get queue size
    pub fn queue_size(&self) -> usize {
        self.queue.lock().unwrap().len()
    }

    /// Clear queue after successful ground uplink
    pub fn clear_queue(&self) {
        self.queue.lock().unwrap().clear();
    }

    /// Remove a specific transaction from queue
    pub fn remove_transaction(&self, txid: &str) -> bool {
        let mut queue = self.queue.lock().unwrap();
        let initial_len = queue.len();
        queue.retain(|tx| tx.txid != txid);
        queue.len() < initial_len
    }

    /// Mark a transaction as attempted (increment retry count)
    pub fn mark_attempted(&self, txid: &str) {
        let mut queue = self.queue.lock().unwrap();
        if let Some(tx) = queue.iter_mut().find(|tx| tx.txid == txid) {
            tx.attempts += 1;
        }
    }

    /// Queue a transaction with priority
    fn queue_transaction(&self, tx: &Transaction, priority: TxPriority) {
        let mut queue = self.queue.lock().unwrap();

        // Remove oldest low-priority transactions if queue is full
        while queue.len() >= self.max_queue_size {
            // Find lowest priority transaction
            if let Some(idx) = queue.iter().enumerate()
                .max_by_key(|(_, tx)| tx.priority)
                .map(|(idx, _)| idx)
            {
                queue.remove(idx);
            } else {
                break;
            }
        }

        let queued = QueuedTransaction {
            tx_hex: hex::encode(bitcoin::consensus::serialize(tx)),
            txid: tx.compute_txid().to_string(),
            priority,
            queued_at: (self.get_timestamp)(),
            attempts: 0,
        };

        queue.push_back(queued);
    }
}

impl Default for SatelliteBroadcaster {
    fn default() -> Self {
        Self::new()
    }
}

impl BroadcasterInterface for SatelliteBroadcaster {
    fn broadcast_transactions(&self, txs: &[&Transaction]) {
        for tx in txs {
            // Determine priority based on transaction characteristics
            // (In practice, LDK provides context about what type of tx this is)
            let priority = TxPriority::Commitment; // Default priority
            self.queue_transaction(tx, priority);

            log::info!(
                "Queued transaction {} for ground uplink (priority: {:?})",
                tx.compute_txid(),
                priority
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use bitcoin::consensus::deserialize;

    fn test_tx() -> Transaction {
        // Minimal valid transaction for testing
        let tx_bytes = hex::decode(
            "0100000001000000000000000000000000000000000000000000000000000000000000000\
             0ffffffff0100ffffffff0100000000000000000000000000"
        ).unwrap();
        deserialize(&tx_bytes).unwrap()
    }

    #[test]
    fn test_queue_transaction() {
        let broadcaster = SatelliteBroadcaster::new();
        let tx = test_tx();

        broadcaster.broadcast_transactions(&[&tx]);

        assert_eq!(broadcaster.queue_size(), 1);
        let queue = broadcaster.get_queue();
        assert_eq!(queue[0].txid, tx.compute_txid().to_string());
    }

    #[test]
    fn test_clear_queue() {
        let broadcaster = SatelliteBroadcaster::new();
        let tx = test_tx();

        broadcaster.broadcast_transactions(&[&tx]);
        assert_eq!(broadcaster.queue_size(), 1);

        broadcaster.clear_queue();
        assert_eq!(broadcaster.queue_size(), 0);
    }

    #[test]
    fn test_remove_transaction() {
        let broadcaster = SatelliteBroadcaster::new();
        let tx = test_tx();
        let txid = tx.compute_txid().to_string();

        broadcaster.broadcast_transactions(&[&tx]);
        assert!(broadcaster.remove_transaction(&txid));
        assert_eq!(broadcaster.queue_size(), 0);
    }
}

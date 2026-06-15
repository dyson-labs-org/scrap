//! Configuration for satellite Lightning nodes

use serde::{Deserialize, Serialize};

/// Configuration for a satellite Lightning node
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SatelliteConfig {
    /// Satellite identifier (e.g., NORAD ID)
    pub satellite_id: String,

    /// Bitcoin network (mainnet, testnet, signet, regtest)
    pub network: Network,

    /// Default fee rate in sat/vB (updated via ground uplink)
    pub default_fee_rate: u32,

    /// Maximum fee rate we're willing to pay
    pub max_fee_rate: u32,

    /// Minimum channel capacity in satoshis
    pub min_channel_capacity_sat: u64,

    /// Maximum channel capacity in satoshis
    pub max_channel_capacity_sat: u64,

    /// Maximum number of channels to maintain
    pub max_channels: usize,

    /// HTLC minimum value in millisatoshis
    pub htlc_minimum_msat: u64,

    /// Maximum HTLC value in flight (msat)
    pub max_htlc_value_in_flight_msat: u64,

    /// Channel reserve (percentage of channel capacity)
    pub channel_reserve_percent: u8,

    /// CLTV expiry delta for forwarded HTLCs
    pub cltv_expiry_delta: u16,

    /// Maximum number of pending HTLCs
    pub max_pending_htlcs: u16,

    /// Ground station contact interval (seconds)
    /// Used for timeout calculations
    pub ground_contact_interval_secs: u64,

    /// Storage configuration
    pub storage: StorageConfig,
}

impl Default for SatelliteConfig {
    fn default() -> Self {
        Self {
            satellite_id: String::from("UNKNOWN"),
            network: Network::Testnet,
            default_fee_rate: 10,
            max_fee_rate: 100,
            min_channel_capacity_sat: 100_000,        // 0.001 BTC
            max_channel_capacity_sat: 10_000_000,     // 0.1 BTC
            max_channels: 10,
            htlc_minimum_msat: 1000,                  // 1 sat
            max_htlc_value_in_flight_msat: 5_000_000_000, // 0.05 BTC
            channel_reserve_percent: 1,
            cltv_expiry_delta: 144,                   // ~1 day
            max_pending_htlcs: 10,
            ground_contact_interval_secs: 5400,      // 90 minutes typical LEO
            storage: StorageConfig::default(),
        }
    }
}

/// Bitcoin network
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Network {
    Mainnet,
    Testnet,
    Signet,
    Regtest,
}

impl From<Network> for bitcoin::Network {
    fn from(n: Network) -> Self {
        match n {
            Network::Mainnet => bitcoin::Network::Bitcoin,
            Network::Testnet => bitcoin::Network::Testnet,
            Network::Signet => bitcoin::Network::Signet,
            Network::Regtest => bitcoin::Network::Regtest,
        }
    }
}

/// Storage configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StorageConfig {
    /// Storage backend type
    pub backend: StorageBackend,

    /// Maximum storage size in bytes
    pub max_size_bytes: usize,

    /// Persist interval (how often to flush to storage)
    pub persist_interval_secs: u64,
}

impl Default for StorageConfig {
    fn default() -> Self {
        Self {
            backend: StorageBackend::Memory,
            max_size_bytes: 1024 * 1024,  // 1 MB
            persist_interval_secs: 60,
        }
    }
}

/// Storage backend types
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum StorageBackend {
    /// In-memory storage (volatile)
    Memory,
    /// Flash storage
    Flash,
    /// Ground-synced storage (periodic uplink)
    GroundSync,
}

/// Timelock configuration for satellite environment
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimelockConfig {
    /// Base CLTV delta (blocks)
    pub base_cltv_delta: u16,

    /// Additional margin per hop (blocks)
    pub margin_per_hop: u16,

    /// Dispute window (blocks)
    pub dispute_window: u16,

    /// Maximum contact gap in blocks
    /// (ground_contact_interval converted to blocks at 10 min/block)
    pub max_contact_gap_blocks: u16,
}

impl Default for TimelockConfig {
    fn default() -> Self {
        Self {
            base_cltv_delta: 144,    // 1 day
            margin_per_hop: 144,     // 1 day per hop
            dispute_window: 36,      // 6 hours
            max_contact_gap_blocks: 12, // 2 hours
        }
    }
}

impl TimelockConfig {
    /// Calculate minimum timeout for a payment with given hop count
    pub fn min_timeout_blocks(&self, hops: u16) -> u32 {
        let final_timeout = self.dispute_window + self.max_contact_gap_blocks + self.margin_per_hop;
        let mut timeout = final_timeout as u32;
        for _ in 1..hops {
            timeout += self.margin_per_hop as u32;
        }
        timeout
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = SatelliteConfig::default();
        assert_eq!(config.network, Network::Testnet);
        assert_eq!(config.cltv_expiry_delta, 144);
    }

    #[test]
    fn test_timelock_calculation() {
        let tl = TimelockConfig::default();

        // 1 hop: 36 + 12 + 144 = 192 blocks
        assert_eq!(tl.min_timeout_blocks(1), 192);

        // 2 hops: 192 + 144 = 336 blocks
        assert_eq!(tl.min_timeout_blocks(2), 336);

        // 3 hops: 336 + 144 = 480 blocks
        assert_eq!(tl.min_timeout_blocks(3), 480);
    }

    #[test]
    fn test_network_conversion() {
        assert_eq!(bitcoin::Network::from(Network::Mainnet), bitcoin::Network::Bitcoin);
        assert_eq!(bitcoin::Network::from(Network::Testnet), bitcoin::Network::Testnet);
    }
}

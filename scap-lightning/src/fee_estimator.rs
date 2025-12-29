//! Fee estimation for satellite environment
//!
//! Satellites cannot query Bitcoin nodes in real-time, so fee rates are:
//! 1. Pre-configured with reasonable defaults
//! 2. Updated periodically via ground station uplink
//! 3. Conservative to avoid stuck transactions

use lightning::chain::chaininterface::{FeeEstimator, ConfirmationTarget};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;

/// Fee estimator for satellite environment
///
/// Uses pre-configured fee rates that can be updated via ground uplink.
/// Fee rates are in satoshis per 1000 weight units (sat/kw).
pub struct SatelliteFeeEstimator {
    /// Fee rate for high-priority transactions (force close, justice)
    high_priority_fee: AtomicU32,
    /// Fee rate for normal transactions (commitment)
    normal_fee: AtomicU32,
    /// Fee rate for low-priority transactions (channel open/close)
    low_priority_fee: AtomicU32,
    /// Minimum acceptable fee rate
    min_fee: AtomicU32,
}

impl SatelliteFeeEstimator {
    /// Create a new fee estimator with default rates
    ///
    /// Default rates are conservative to work in most fee environments.
    pub fn new() -> Self {
        Self {
            high_priority_fee: AtomicU32::new(5000),  // 20 sat/vB
            normal_fee: AtomicU32::new(2500),         // 10 sat/vB
            low_priority_fee: AtomicU32::new(1250),   // 5 sat/vB
            min_fee: AtomicU32::new(253),             // 1 sat/vB minimum
        }
    }

    /// Create a fee estimator with custom rates (in sat/kw)
    pub fn with_rates(high: u32, normal: u32, low: u32, min: u32) -> Self {
        Self {
            high_priority_fee: AtomicU32::new(high),
            normal_fee: AtomicU32::new(normal),
            low_priority_fee: AtomicU32::new(low),
            min_fee: AtomicU32::new(min),
        }
    }

    /// Create an Arc-wrapped estimator (commonly needed for LDK)
    pub fn arc() -> Arc<Self> {
        Arc::new(Self::new())
    }

    /// Update fee rates from ground station uplink
    ///
    /// Rates are in sat/vB and will be converted to sat/kw internally.
    pub fn update_from_ground(&self, high_sat_vb: u32, normal_sat_vb: u32, low_sat_vb: u32) {
        // Convert sat/vB to sat/kw (multiply by 250)
        self.high_priority_fee.store(high_sat_vb * 250, Ordering::Release);
        self.normal_fee.store(normal_sat_vb * 250, Ordering::Release);
        self.low_priority_fee.store(low_sat_vb * 250, Ordering::Release);
    }

    /// Get current fee rates (in sat/vB for display)
    pub fn get_rates(&self) -> FeeRates {
        FeeRates {
            high_sat_vb: self.high_priority_fee.load(Ordering::Acquire) / 250,
            normal_sat_vb: self.normal_fee.load(Ordering::Acquire) / 250,
            low_sat_vb: self.low_priority_fee.load(Ordering::Acquire) / 250,
            min_sat_vb: self.min_fee.load(Ordering::Acquire) / 250,
        }
    }
}

impl Default for SatelliteFeeEstimator {
    fn default() -> Self {
        Self::new()
    }
}

impl FeeEstimator for SatelliteFeeEstimator {
    fn get_est_sat_per_1000_weight(&self, confirmation_target: ConfirmationTarget) -> u32 {
        let fee = match confirmation_target {
            // Urgent: justice transactions, force close sweeps
            ConfirmationTarget::UrgentOnChainSweep => {
                self.high_priority_fee.load(Ordering::Acquire)
            }
            // High priority: commitment transactions
            ConfirmationTarget::MinAllowedNonAnchorChannelRemoteFee |
            ConfirmationTarget::NonAnchorChannelFee |
            ConfirmationTarget::AnchorChannelFee => {
                self.normal_fee.load(Ordering::Acquire)
            }
            // Normal: channel funding
            ConfirmationTarget::ChannelCloseMinimum |
            ConfirmationTarget::OutputSpendingFee => {
                self.low_priority_fee.load(Ordering::Acquire)
            }
            // Minimum relay fee
            ConfirmationTarget::MinAllowedAnchorChannelRemoteFee => {
                self.min_fee.load(Ordering::Acquire)
            }
            // Maximum fee estimate (for fee bumping upper bound)
            ConfirmationTarget::MaximumFeeEstimate => {
                self.high_priority_fee.load(Ordering::Acquire) * 2
            }
        };

        // Never go below minimum
        let min = self.min_fee.load(Ordering::Acquire);
        fee.max(min)
    }
}

/// Current fee rates for display/logging
#[derive(Debug, Clone, Copy)]
pub struct FeeRates {
    pub high_sat_vb: u32,
    pub normal_sat_vb: u32,
    pub low_sat_vb: u32,
    pub min_sat_vb: u32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_fee_rates() {
        let estimator = SatelliteFeeEstimator::new();
        let rates = estimator.get_rates();

        assert_eq!(rates.high_sat_vb, 20);
        assert_eq!(rates.normal_sat_vb, 10);
        assert_eq!(rates.low_sat_vb, 5);
    }

    #[test]
    fn test_update_from_ground() {
        let estimator = SatelliteFeeEstimator::new();
        estimator.update_from_ground(50, 25, 10);

        let rates = estimator.get_rates();
        assert_eq!(rates.high_sat_vb, 50);
        assert_eq!(rates.normal_sat_vb, 25);
        assert_eq!(rates.low_sat_vb, 10);
    }

    #[test]
    fn test_fee_estimation() {
        let estimator = SatelliteFeeEstimator::new();

        let urgent = estimator.get_est_sat_per_1000_weight(ConfirmationTarget::UrgentOnChainSweep);
        let normal = estimator.get_est_sat_per_1000_weight(ConfirmationTarget::NonAnchorChannelFee);

        assert!(urgent > normal);
    }
}

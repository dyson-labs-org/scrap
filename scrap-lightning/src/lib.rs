//! SCRAP Lightning Integration
//!
//! LDK integration for satellite-to-satellite payments using the Lightning Network.
//!
//! This module provides satellite-specific implementations of LDK traits:
//!
//! - [`SatellitePersister`] - Stores channel state in satellite storage
//! - [`SatelliteFeeEstimator`] - Uses pre-configured fee rates (no real-time Bitcoin node access)
//! - [`SatelliteBroadcaster`] - Queues transactions for ground station uplink
//! - [`SatelliteLogger`] - Integrates with satellite telemetry
//!
//! # Architecture
//!
//! ```text
//! ┌─────────────────────────────────────────────────────────────┐
//! │                    SCRAP Lightning Node                       │
//! ├─────────────────────────────────────────────────────────────┤
//! │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
//! │  │ Channel     │  │ Payment     │  │ SCRAP Task           │  │
//! │  │ Manager     │  │ Router      │  │ Binding             │  │
//! │  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
//! │         │                │                    │             │
//! │  ┌──────┴────────────────┴────────────────────┴──────────┐  │
//! │  │                    LDK Core                            │  │
//! │  └──────┬──────────────┬────────────────┬────────────────┘  │
//! │         │              │                │                   │
//! │  ┌──────┴──────┐ ┌─────┴─────┐ ┌────────┴────────┐         │
//! │  │ Persister   │ │ Fee Est.  │ │ Broadcaster     │         │
//! │  │ (RAM/Flash) │ │ (Config)  │ │ (Ground Queue)  │         │
//! │  └─────────────┘ └───────────┘ └─────────────────┘         │
//! └─────────────────────────────────────────────────────────────┘
//! ```

pub mod persister;
pub mod fee_estimator;
pub mod broadcaster;
pub mod logger;
pub mod channel;
pub mod payment;
pub mod binding;
pub mod config;

pub use persister::SatellitePersister;
pub use fee_estimator::SatelliteFeeEstimator;
pub use broadcaster::SatelliteBroadcaster;
pub use logger::SatelliteLogger;
pub use channel::SatelliteChannelManager;
pub use payment::{PaymentInfo, PaymentStatus};
pub use binding::TaskPaymentBinding;
pub use config::SatelliteConfig;

/// Re-export commonly used LDK types
pub mod ldk {
    pub use lightning::ln::channelmanager::{ChannelManager, ChannelManagerReadArgs};
    pub use lightning::ln::peer_handler::PeerManager;
    pub use lightning::chain::chaininterface::{BroadcasterInterface, FeeEstimator};
    pub use lightning::sign::KeysManager;
    pub use lightning::util::persist::Persister;
    pub use lightning::events::Event;
}

/// Library version
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

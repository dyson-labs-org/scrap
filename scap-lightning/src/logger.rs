//! Satellite-compatible logging for LDK

use lightning::util::logger::{Logger, Record};
use log::{Level, log};
use std::sync::Arc;

/// Logger that integrates with satellite telemetry
pub struct SatelliteLogger {
    /// Satellite identifier for log context
    satellite_id: String,
    /// Minimum log level
    min_level: lightning::util::logger::Level,
}

impl SatelliteLogger {
    /// Create a new satellite logger
    pub fn new(satellite_id: String) -> Self {
        Self {
            satellite_id,
            min_level: lightning::util::logger::Level::Info,
        }
    }

    /// Create a new logger with custom minimum level
    pub fn with_level(satellite_id: String, min_level: lightning::util::logger::Level) -> Self {
        Self {
            satellite_id,
            min_level,
        }
    }

    /// Create an Arc-wrapped logger (commonly needed for LDK)
    pub fn arc(satellite_id: String) -> Arc<Self> {
        Arc::new(Self::new(satellite_id))
    }
}

impl Logger for SatelliteLogger {
    fn log(&self, record: Record) {
        if record.level < self.min_level {
            return;
        }

        let level = match record.level {
            lightning::util::logger::Level::Gossip => Level::Trace,
            lightning::util::logger::Level::Trace => Level::Trace,
            lightning::util::logger::Level::Debug => Level::Debug,
            lightning::util::logger::Level::Info => Level::Info,
            lightning::util::logger::Level::Warn => Level::Warn,
            lightning::util::logger::Level::Error => Level::Error,
        };

        log!(
            level,
            "[{}][LDK][{}:{}] {}",
            self.satellite_id,
            record.module_path,
            record.line,
            record.args
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_logger_creation() {
        let logger = SatelliteLogger::new("SAT-001".to_string());
        assert_eq!(logger.satellite_id, "SAT-001");
    }

    #[test]
    fn test_arc_logger() {
        let logger = SatelliteLogger::arc("SAT-002".to_string());
        assert_eq!(logger.satellite_id, "SAT-002");
    }
}

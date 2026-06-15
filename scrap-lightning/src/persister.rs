//! Satellite storage for Lightning channel state
//!
//! Satellites need to persist channel state to survive reboots and ensure
//! funds can be recovered. This module provides storage backends suitable
//! for satellite environments.

use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use serde::{Serialize, Deserialize};

/// In-memory persister for satellite channel state
///
/// This persister stores data in RAM and can optionally serialize to
/// a byte buffer for ground uplink backup.
pub struct SatellitePersister {
    /// Channel monitors (keyed by funding outpoint)
    monitors: RwLock<HashMap<String, Vec<u8>>>,
    /// Channel manager state
    manager: RwLock<Option<Vec<u8>>>,
    /// Network graph
    graph: RwLock<Option<Vec<u8>>>,
    /// Scorer state
    scorer: RwLock<Option<Vec<u8>>>,
    /// Maximum total storage size
    max_size: usize,
    /// Current storage usage
    current_size: RwLock<usize>,
}

impl SatellitePersister {
    /// Create a new persister with default size limit (1MB)
    pub fn new() -> Self {
        Self::with_max_size(1024 * 1024)
    }

    /// Create a persister with custom size limit
    pub fn with_max_size(max_size: usize) -> Self {
        Self {
            monitors: RwLock::new(HashMap::new()),
            manager: RwLock::new(None),
            graph: RwLock::new(None),
            scorer: RwLock::new(None),
            max_size,
            current_size: RwLock::new(0),
        }
    }

    /// Create an Arc-wrapped persister
    pub fn arc() -> Arc<Self> {
        Arc::new(Self::new())
    }

    /// Get current storage usage in bytes
    pub fn storage_used(&self) -> usize {
        *self.current_size.read().unwrap()
    }

    /// Get storage capacity remaining
    pub fn storage_available(&self) -> usize {
        self.max_size.saturating_sub(self.storage_used())
    }

    /// Persist a channel monitor
    pub fn persist_monitor(&self, key: &str, data: Vec<u8>) -> Result<(), PersistError> {
        let data_len = data.len();

        let mut monitors = self.monitors.write().unwrap();
        let mut current_size = self.current_size.write().unwrap();

        // Remove old size if updating
        if let Some(old) = monitors.get(key) {
            *current_size = current_size.saturating_sub(old.len());
        }

        // Check capacity
        if *current_size + data_len > self.max_size {
            return Err(PersistError::StorageFull);
        }

        monitors.insert(key.to_string(), data);
        *current_size += data_len;

        Ok(())
    }

    /// Load a channel monitor
    pub fn load_monitor(&self, key: &str) -> Option<Vec<u8>> {
        self.monitors.read().unwrap().get(key).cloned()
    }

    /// List all monitor keys
    pub fn list_monitors(&self) -> Vec<String> {
        self.monitors.read().unwrap().keys().cloned().collect()
    }

    /// Persist channel manager state
    pub fn persist_manager(&self, data: Vec<u8>) -> Result<(), PersistError> {
        let data_len = data.len();

        let mut manager = self.manager.write().unwrap();
        let mut current_size = self.current_size.write().unwrap();

        if let Some(ref old) = *manager {
            *current_size = current_size.saturating_sub(old.len());
        }

        if *current_size + data_len > self.max_size {
            return Err(PersistError::StorageFull);
        }

        *manager = Some(data);
        *current_size += data_len;

        Ok(())
    }

    /// Load channel manager state
    pub fn load_manager(&self) -> Option<Vec<u8>> {
        self.manager.read().unwrap().clone()
    }

    /// Persist network graph
    pub fn persist_graph(&self, data: Vec<u8>) -> Result<(), PersistError> {
        let data_len = data.len();

        let mut graph = self.graph.write().unwrap();
        let mut current_size = self.current_size.write().unwrap();

        if let Some(ref old) = *graph {
            *current_size = current_size.saturating_sub(old.len());
        }

        if *current_size + data_len > self.max_size {
            return Err(PersistError::StorageFull);
        }

        *graph = Some(data);
        *current_size += data_len;

        Ok(())
    }

    /// Load network graph
    pub fn load_graph(&self) -> Option<Vec<u8>> {
        self.graph.read().unwrap().clone()
    }

    /// Persist scorer state
    pub fn persist_scorer(&self, data: Vec<u8>) -> Result<(), PersistError> {
        let data_len = data.len();

        let mut scorer = self.scorer.write().unwrap();
        let mut current_size = self.current_size.write().unwrap();

        if let Some(ref old) = *scorer {
            *current_size = current_size.saturating_sub(old.len());
        }

        if *current_size + data_len > self.max_size {
            return Err(PersistError::StorageFull);
        }

        *scorer = Some(data);
        *current_size += data_len;

        Ok(())
    }

    /// Load scorer state
    pub fn load_scorer(&self) -> Option<Vec<u8>> {
        self.scorer.read().unwrap().clone()
    }

    /// Export all state for ground backup
    pub fn export_all(&self) -> StorageSnapshot {
        StorageSnapshot {
            monitors: self.monitors.read().unwrap().clone(),
            manager: self.manager.read().unwrap().clone(),
            graph: self.graph.read().unwrap().clone(),
            scorer: self.scorer.read().unwrap().clone(),
        }
    }

    /// Import state from ground restore
    pub fn import_all(&self, snapshot: StorageSnapshot) -> Result<(), PersistError> {
        let total_size: usize = snapshot.monitors.values().map(|v| v.len()).sum::<usize>()
            + snapshot.manager.as_ref().map(|v| v.len()).unwrap_or(0)
            + snapshot.graph.as_ref().map(|v| v.len()).unwrap_or(0)
            + snapshot.scorer.as_ref().map(|v| v.len()).unwrap_or(0);

        if total_size > self.max_size {
            return Err(PersistError::StorageFull);
        }

        *self.monitors.write().unwrap() = snapshot.monitors;
        *self.manager.write().unwrap() = snapshot.manager;
        *self.graph.write().unwrap() = snapshot.graph;
        *self.scorer.write().unwrap() = snapshot.scorer;
        *self.current_size.write().unwrap() = total_size;

        Ok(())
    }

    /// Clear all stored data
    pub fn clear(&self) {
        self.monitors.write().unwrap().clear();
        *self.manager.write().unwrap() = None;
        *self.graph.write().unwrap() = None;
        *self.scorer.write().unwrap() = None;
        *self.current_size.write().unwrap() = 0;
    }
}

impl Default for SatellitePersister {
    fn default() -> Self {
        Self::new()
    }
}

/// Storage snapshot for backup/restore
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StorageSnapshot {
    pub monitors: HashMap<String, Vec<u8>>,
    pub manager: Option<Vec<u8>>,
    pub graph: Option<Vec<u8>>,
    pub scorer: Option<Vec<u8>>,
}

/// Persistence errors
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PersistError {
    /// Storage capacity exceeded
    StorageFull,
    /// I/O error
    IoError(String),
    /// Serialization error
    SerializationError(String),
}

impl std::fmt::Display for PersistError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::StorageFull => write!(f, "storage capacity exceeded"),
            Self::IoError(msg) => write!(f, "I/O error: {}", msg),
            Self::SerializationError(msg) => write!(f, "serialization error: {}", msg),
        }
    }
}

impl std::error::Error for PersistError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_persist_monitor() {
        let persister = SatellitePersister::new();
        let data = vec![1, 2, 3, 4, 5];

        persister.persist_monitor("channel-1", data.clone()).unwrap();

        let loaded = persister.load_monitor("channel-1").unwrap();
        assert_eq!(loaded, data);
    }

    #[test]
    fn test_storage_tracking() {
        let persister = SatellitePersister::with_max_size(1000);

        let data = vec![0u8; 100];
        persister.persist_monitor("ch-1", data.clone()).unwrap();
        assert_eq!(persister.storage_used(), 100);

        persister.persist_manager(data.clone()).unwrap();
        assert_eq!(persister.storage_used(), 200);
    }

    #[test]
    fn test_storage_full() {
        let persister = SatellitePersister::with_max_size(100);

        let data = vec![0u8; 150];
        let result = persister.persist_monitor("ch-1", data);

        assert_eq!(result, Err(PersistError::StorageFull));
    }

    #[test]
    fn test_export_import() {
        let persister1 = SatellitePersister::new();
        persister1.persist_monitor("ch-1", vec![1, 2, 3]).unwrap();
        persister1.persist_manager(vec![4, 5, 6]).unwrap();

        let snapshot = persister1.export_all();

        let persister2 = SatellitePersister::new();
        persister2.import_all(snapshot).unwrap();

        assert_eq!(persister2.load_monitor("ch-1"), Some(vec![1, 2, 3]));
        assert_eq!(persister2.load_manager(), Some(vec![4, 5, 6]));
    }

    #[test]
    fn test_list_monitors() {
        let persister = SatellitePersister::new();
        persister.persist_monitor("ch-1", vec![1]).unwrap();
        persister.persist_monitor("ch-2", vec![2]).unwrap();

        let monitors = persister.list_monitors();
        assert_eq!(monitors.len(), 2);
        assert!(monitors.contains(&"ch-1".to_string()));
        assert!(monitors.contains(&"ch-2".to_string()));
    }
}

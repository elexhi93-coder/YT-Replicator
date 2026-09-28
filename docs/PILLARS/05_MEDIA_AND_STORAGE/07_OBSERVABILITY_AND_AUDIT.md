# 07 — Observability and Audit: Media & Storage

**Pillar:** 5 · Media & Storage · **Chapter:** Observability and Audit · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §8  
**Depends on:** `docs/PILLARS/05_MEDIA_AND_STORAGE/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-2, INV-3, INV-6, INV-10  

---

## 1. Domain Event Registry

| Event Name | Trigger Condition | Payload Key Attributes | Purpose |
|---|---|---|---|
| `media.download.started` | yt-dlp initiates stream acquisition | `asset_id`, `catalog_video_id`, `root_path` | I/O monitoring |
| `media.asset.verified` | SHA-256 and non-zero size confirmed | `asset_id`, `byte_size`, `sha256` | Handover to upload engine (`INV-3`) |
| `media.retention.dry_run`| Dry-run evaluation completed | `total_candidates`, `total_bytes` | Preview audit trail (`INV-10`) |
| `media.retention.pruned` | Physical file removed from disk | `asset_id`, `bytes_reclaimed`, `reason` | Immutable deletion ledger |
| `media.root.unmounted` | External storage volume unmounted | `storage_root_id`, `base_path` | Transition to `ARCHIVE_OFFLINE` |
| `media.orphan.reaped` | Abandoned `.part` file removed | `filename`, `bytes_reclaimed` | Hygiene telemetry |

---

## 2. Real-Time Prometheus Metrics

```prometheus
# HELP ytr_storage_free_bytes Free storage remaining on root volume.
# TYPE ytr_storage_free_bytes gauge
ytr_storage_free_bytes{root="/data/media"} 219043332096

# HELP ytr_storage_used_bytes Total storage consumed by ON_DISK assets.
# TYPE ytr_storage_used_bytes gauge
ytr_storage_used_bytes{root="/data/media"} 1932735283200

# HELP ytr_media_assets_total Current count of assets by state.
# TYPE ytr_media_assets_total gauge
ytr_media_assets_total{state="ON_DISK"} 412
ytr_media_assets_total{state="DOWNLOADING"} 2
ytr_media_assets_total{state="ARCHIVE_OFFLINE"} 0

# HELP ytr_retention_reclaimed_bytes_total Cumulative bytes safely reclaimed by retention sweeper.
# TYPE ytr_retention_reclaimed_bytes_total counter
ytr_retention_reclaimed_bytes_total 45812903844

# HELP ytr_media_download_duration_seconds Latency of yt-dlp acquisitions.
# TYPE ytr_media_download_duration_seconds histogram
```

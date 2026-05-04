import { useState, useEffect, useRef, useCallback } from "react";

const API = "http://localhost:8000";

// ─── Utility ────────────────────────────────────────────────────────────────

const fmt = (s) => {
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(1).padStart(4, "0");
  return `${m}:${sec}`;
};

const hslColor = (id) => {
  const n = parseInt(id.replace("P", ""));
  return `hsl(${(n * 137) % 360}, 72%, 55%)`;
};

// ─── Components ─────────────────────────────────────────────────────────────

function UploadPanel({ onProcessed }) {
  const [dragging, setDragging] = useState(false);
  const [file, setFile]         = useState(null);
  const [jobId, setJobId]       = useState(null);
  const [progress, setProgress] = useState(0);
  const [status, setStatus]     = useState("");
  const [phase, setPhase]       = useState("idle"); // idle | uploading | processing | done | error
  const pollRef = useRef(null);

  const handleFile = (f) => {
    if (!f?.type.startsWith("video/")) return;
    setFile(f);
    setPhase("idle");
    setProgress(0);
    setStatus("");
  };

  const startUpload = async () => {
    if (!file) return;
    setPhase("uploading");
    setStatus("Uploading…");

    const fd = new FormData();
    fd.append("file", file);

    try {
      const res  = await fetch(`${API}/api/upload`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      setJobId(data.job_id);
      setPhase("processing");
      pollJob(data.job_id);
    } catch (e) {
      setPhase("error");
      setStatus(e.message);
    }
  };

  const pollJob = (jid) => {
    pollRef.current = setInterval(async () => {
      try {
        const res  = await fetch(`${API}/api/jobs/${jid}`);
        const data = await res.json();
        setProgress(data.progress);
        setStatus(data.message);

        if (data.status === "done") {
          clearInterval(pollRef.current);
          setPhase("done");
          onProcessed(jid);
        } else if (data.status === "error") {
          clearInterval(pollRef.current);
          setPhase("error");
        }
      } catch {}
    }, 1500);
  };

  useEffect(() => () => clearInterval(pollRef.current), []);

  return (
    <div style={styles.uploadWrap}>
      <div style={styles.logo}>
        <span style={styles.logoIcon}>◈</span>
        <span style={styles.logoText}>SENTINEL</span>
        <span style={styles.logoSub}>Video Intelligence</span>
      </div>

      <div
        style={{ ...styles.dropZone, ...(dragging ? styles.dropZoneActive : {}) }}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]); }}
        onClick={() => document.getElementById("fileInput").click()}
      >
        <input
          id="fileInput" type="file" accept="video/*"
          style={{ display: "none" }}
          onChange={(e) => handleFile(e.target.files[0])}
        />
        <div style={styles.dropIcon}>{file ? "🎬" : "⬆"}</div>
        {file
          ? <p style={styles.dropText}>{file.name}</p>
          : <p style={styles.dropText}>Drop CCTV video here<br/><span style={styles.dropHint}>MP4 · AVI · MOV · MKV</span></p>
        }
      </div>

      {file && phase === "idle" && (
        <button style={styles.analyzeBtn} onClick={startUpload}>
          Analyze Video
        </button>
      )}

      {(phase === "uploading" || phase === "processing") && (
        <div style={styles.progressWrap}>
          <div style={styles.progressBar}>
            <div style={{ ...styles.progressFill, width: `${progress}%` }} />
          </div>
          <p style={styles.progressLabel}>{status} — {progress}%</p>
        </div>
      )}

      {phase === "error" && (
        <p style={styles.errorMsg}>⚠ {status}</p>
      )}
    </div>
  );
}


function PersonCard({ person, selected, onClick }) {
  const color = hslColor(person.person_id);
  return (
    <div
      style={{
        ...styles.personCard,
        ...(selected ? { borderColor: color, background: "rgba(255,255,255,0.04)" } : {}),
      }}
      onClick={() => onClick(person.person_id)}
    >
      <div style={{ ...styles.personAvatar, borderColor: color }}>
        {person.thumbnail
          ? <img src={`${API}${person.thumbnail}`} alt={person.person_id}
                 style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: "50%" }} />
          : <span style={{ color, fontSize: 16, fontWeight: 700 }}>{person.person_id}</span>
        }
      </div>
      <div style={styles.personInfo}>
        <div style={{ color, fontWeight: 700, fontSize: 13 }}>{person.person_id}</div>
        <div style={styles.personMeta}>{fmt(person.first_seen)} → {fmt(person.last_seen)}</div>
        <div style={styles.personMeta}>{person.appearances} appearances</div>
      </div>
      {selected && <div style={{ ...styles.selectedDot, background: color }} />}
    </div>
  );
}


function Timeline({ timestamps, duration, currentTime, onSeek, color }) {
  const ref = useRef(null);

  const handleClick = (e) => {
    const rect  = ref.current.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    onSeek(ratio * duration);
  };

  return (
    <div ref={ref} style={styles.timeline} onClick={handleClick} title="Click to seek">
      {/* current position */}
      <div style={{
        ...styles.timelineHead,
        left: `${(currentTime / duration) * 100}%`,
      }} />
      {/* appearance markers */}
      {timestamps.map((t, i) => (
        <div
          key={i}
          style={{
            ...styles.timelineMark,
            left: `${(t / duration) * 100}%`,
            background: color,
          }}
        />
      ))}
    </div>
  );
}


function HeatmapModal({ src, onClose }) {
  return (
    <div style={styles.modalOverlay} onClick={onClose}>
      <div style={styles.modalBox} onClick={(e) => e.stopPropagation()}>
        <button style={styles.modalClose} onClick={onClose}>✕</button>
        <img src={`${API}${src}`} alt="Heatmap" style={{ maxWidth: "100%", borderRadius: 8 }} />
      </div>
    </div>
  );
}


// ─── Main App ────────────────────────────────────────────────────────────────

export default function App() {
  const [jobId, setJobId]           = useState(null);
  const [persons, setPersons]       = useState([]);
  const [selected, setSelected]     = useState(null);
  const [detail, setDetail]         = useState(null);
  const [searchQ, setSearchQ]       = useState("");
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration]     = useState(0);
  const [heatmapSrc, setHeatmapSrc] = useState(null);
  const videoRef = useRef(null);

  // fetch person list after job done
  useEffect(() => {
    if (!jobId) return;
    fetch(`${API}/api/persons`)
      .then((r) => r.json())
      .then(setPersons)
      .catch(() => {});
  }, [jobId]);

  // fetch detail when selection changes
  useEffect(() => {
    if (!selected) return;
    fetch(`${API}/api/persons/${selected}`)
      .then((r) => r.json())
      .then(setDetail)
      .catch(() => {});
  }, [selected]);

  const handleSearch = (e) => {
    e.preventDefault();
    const q = searchQ.trim().toUpperCase();
    if (q) setSelected(q);
  };

  const handlePersonClick = (pid) => {
    setSelected(pid);
    // jump to first appearance
    const p = persons.find((x) => x.person_id === pid);
    if (p && videoRef.current) videoRef.current.currentTime = p.first_seen;
  };

  const handleSeek = (t) => {
    if (videoRef.current) videoRef.current.currentTime = t;
  };

  const color = selected ? hslColor(selected) : "#4ade80";

  if (!jobId) return <UploadPanel onProcessed={setJobId} />;

  return (
    <div style={styles.appShell}>
      {/* ── Sidebar ───────────────────── */}
      <aside style={styles.sidebar}>
        <div style={styles.sidebarHeader}>
          <span style={styles.logoIcon}>◈</span>
          <span style={styles.logoText}>SENTINEL</span>
        </div>

        {/* Search */}
        <form onSubmit={handleSearch} style={styles.searchForm}>
          <input
            style={styles.searchInput}
            placeholder="Search P1, P2…"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
          />
          <button type="submit" style={styles.searchBtn}>→</button>
        </form>

        {/* Person list */}
        <div style={styles.personList}>
          {persons.map((p) => (
            <PersonCard
              key={p.person_id}
              person={p}
              selected={selected === p.person_id}
              onClick={handlePersonClick}
            />
          ))}
          {persons.length === 0 && (
            <p style={{ color: "#555", fontSize: 12, padding: "12px 16px" }}>
              No persons tracked yet.
            </p>
          )}
        </div>
      </aside>

      {/* ── Main panel ────────────────── */}
      <main style={styles.main}>
        {/* Video */}
        <div style={styles.videoWrap}>
          <video
            ref={videoRef}
            src={`${API}/api/video/${jobId}`}
            style={styles.video}
            controls
            onTimeUpdate={(e) => setCurrentTime(e.target.currentTime)}
            onLoadedMetadata={(e) => setDuration(e.target.duration)}
          />
          {/* overlay label */}
          {selected && (
            <div style={{ ...styles.videoLabel, color }}>
              ● {selected} selected
            </div>
          )}
        </div>

        {/* Timeline */}
        {detail && duration > 0 && (
          <div style={styles.timelineWrap}>
            <span style={{ ...styles.tlLabel, color }}>
              {detail.person_id}
            </span>
            <Timeline
              timestamps={detail.timestamps}
              duration={duration}
              currentTime={currentTime}
              onSeek={handleSeek}
              color={color}
            />
            <span style={styles.tlTime}>{fmt(currentTime)} / {fmt(duration)}</span>
          </div>
        )}

        {/* Detail panel */}
        {detail && (
          <div style={styles.detailPanel}>
            <div style={styles.detailRow}>
              <Stat label="First Seen" value={fmt(detail.first_seen)} />
              <Stat label="Last Seen"  value={fmt(detail.last_seen)} />
              <Stat label="On Screen"  value={`${detail.total_time.toFixed(1)}s`} />
              <Stat label="Appearances" value={detail.appearances} />
            </div>

            <div style={styles.detailActions}>
              <button
                style={styles.actionBtn}
                onClick={() => handleSeek(detail.first_seen)}
              >⏮ First appearance</button>

              <button
                style={styles.actionBtn}
                onClick={() => handleSeek(detail.last_seen)}
              >⏭ Last appearance</button>

              {detail.heatmap && (
                <button
                  style={{ ...styles.actionBtn, borderColor: color, color }}
                  onClick={() => setHeatmapSrc(detail.heatmap)}
                >⬡ View Heatmap</button>
              )}
            </div>

            {/* Mini timestamp list */}
            <div style={styles.timestampScroll}>
              {detail.timestamps.slice(0, 80).map((t, i) => (
                <button
                  key={i}
                  style={{
                    ...styles.tsChip,
                    ...(Math.abs(currentTime - t) < 0.5
                      ? { background: color, color: "#000" } : {}),
                  }}
                  onClick={() => handleSeek(t)}
                >
                  {fmt(t)}
                </button>
              ))}
              {detail.timestamps.length > 80 && (
                <span style={{ color: "#555", fontSize: 11 }}>
                  +{detail.timestamps.length - 80} more
                </span>
              )}
            </div>
          </div>
        )}
      </main>

      {heatmapSrc && (
        <HeatmapModal src={heatmapSrc} onClose={() => setHeatmapSrc(null)} />
      )}
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div style={styles.statBox}>
      <div style={styles.statVal}>{value}</div>
      <div style={styles.statLabel}>{label}</div>
    </div>
  );
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const styles = {
  // Upload screen
  uploadWrap: {
    minHeight: "100vh", background: "#080c10",
    display: "flex", flexDirection: "column",
    alignItems: "center", justifyContent: "center",
    fontFamily: "'DM Mono', monospace",
    gap: 28,
  },
  logo: {
    display: "flex", alignItems: "baseline", gap: 10,
  },
  logoIcon: { fontSize: 28, color: "#4ade80" },
  logoText: { fontSize: 22, fontWeight: 800, letterSpacing: 4, color: "#e8f5e9" },
  logoSub: { fontSize: 11, color: "#4ade80", letterSpacing: 2 },

  dropZone: {
    width: 420, padding: "40px 32px",
    border: "2px dashed #2a3a2a",
    borderRadius: 12, textAlign: "center",
    cursor: "pointer", transition: "all .2s",
    background: "#0d150d",
  },
  dropZoneActive: { borderColor: "#4ade80", background: "#0a1a0a" },
  dropIcon: { fontSize: 36, marginBottom: 12 },
  dropText: { color: "#b0c4b1", fontSize: 14, lineHeight: 1.7, margin: 0 },
  dropHint: { fontSize: 11, color: "#4a6a4a" },

  analyzeBtn: {
    padding: "12px 36px", background: "#4ade80",
    color: "#000", border: "none", borderRadius: 8,
    fontFamily: "'DM Mono', monospace", fontWeight: 700,
    fontSize: 14, cursor: "pointer", letterSpacing: 1,
  },
  progressWrap: { width: 420 },
  progressBar: { height: 4, background: "#1a2a1a", borderRadius: 4, overflow: "hidden" },
  progressFill: { height: "100%", background: "#4ade80", transition: "width .3s" },
  progressLabel: { color: "#4a6a4a", fontSize: 12, marginTop: 8, textAlign: "center" },
  errorMsg: { color: "#f87171", fontSize: 13 },

  // App shell
  appShell: {
    display: "flex", height: "100vh",
    background: "#07090c", color: "#cdd5d1",
    fontFamily: "'DM Mono', monospace",
    overflow: "hidden",
  },

  // Sidebar
  sidebar: {
    width: 240, borderRight: "1px solid #111c14",
    display: "flex", flexDirection: "column",
    background: "#07090c", flexShrink: 0,
  },
  sidebarHeader: {
    padding: "16px 18px", borderBottom: "1px solid #111c14",
    display: "flex", alignItems: "center", gap: 8,
  },
  searchForm: {
    display: "flex", padding: "12px 12px 8px",
    gap: 6,
  },
  searchInput: {
    flex: 1, background: "#0d130d",
    border: "1px solid #1a2a1a",
    color: "#b0c4b1", fontSize: 12,
    padding: "7px 10px", borderRadius: 6,
    fontFamily: "inherit", outline: "none",
  },
  searchBtn: {
    background: "#1a2e1a", border: "none",
    color: "#4ade80", width: 32, borderRadius: 6,
    cursor: "pointer", fontSize: 16,
  },
  personList: { flex: 1, overflowY: "auto", padding: "4px 0" },

  personCard: {
    display: "flex", alignItems: "center", gap: 10,
    padding: "9px 14px", cursor: "pointer",
    borderLeft: "3px solid transparent",
    transition: "all .15s",
    position: "relative",
  },
  personAvatar: {
    width: 38, height: 38, borderRadius: "50%",
    border: "2px solid", display: "flex",
    alignItems: "center", justifyContent: "center",
    overflow: "hidden", flexShrink: 0,
    background: "#0d150d",
  },
  personInfo: { flex: 1, minWidth: 0 },
  personMeta: { color: "#4a6a4a", fontSize: 10, lineHeight: 1.6 },
  selectedDot: { width: 6, height: 6, borderRadius: "50%" },

  // Main
  main: {
    flex: 1, display: "flex", flexDirection: "column",
    overflow: "hidden",
  },
  videoWrap: {
    flex: "0 0 auto", position: "relative",
    background: "#000", maxHeight: "55vh",
  },
  video: {
    width: "100%", maxHeight: "55vh",
    display: "block", objectFit: "contain",
  },
  videoLabel: {
    position: "absolute", top: 12, right: 14,
    fontSize: 12, fontWeight: 700,
    letterSpacing: 1, background: "rgba(0,0,0,.6)",
    padding: "4px 10px", borderRadius: 4,
  },

  // Timeline
  timelineWrap: {
    display: "flex", alignItems: "center", gap: 10,
    padding: "10px 16px", borderBottom: "1px solid #111c14",
    flexShrink: 0,
  },
  tlLabel: { fontSize: 12, fontWeight: 700, minWidth: 32 },
  tlTime: { fontSize: 11, color: "#4a6a4a", minWidth: 90, textAlign: "right" },
  timeline: {
    flex: 1, height: 28, background: "#0d150d",
    borderRadius: 4, position: "relative",
    cursor: "crosshair", border: "1px solid #1a2a1a",
    overflow: "hidden",
  },
  timelineHead: {
    position: "absolute", top: 0, width: 2,
    height: "100%", background: "#fff", opacity: .7,
    pointerEvents: "none",
  },
  timelineMark: {
    position: "absolute", top: "20%",
    width: 2, height: "60%", borderRadius: 1,
    opacity: .8, pointerEvents: "none",
  },

  // Detail
  detailPanel: {
    flex: 1, overflowY: "auto", padding: "14px 18px",
  },
  detailRow: { display: "flex", gap: 12, marginBottom: 14 },
  statBox: {
    flex: 1, background: "#0d130d",
    border: "1px solid #1a2a1a",
    borderRadius: 8, padding: "10px 12px",
    textAlign: "center",
  },
  statVal:   { fontSize: 17, fontWeight: 700, color: "#e8f5e9" },
  statLabel: { fontSize: 10, color: "#4a6a4a", marginTop: 4 },

  detailActions: { display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" },
  actionBtn: {
    padding: "7px 14px", background: "transparent",
    border: "1px solid #1a2a1a",
    color: "#b0c4b1", borderRadius: 6,
    fontFamily: "inherit", fontSize: 11,
    cursor: "pointer",
  },

  timestampScroll: {
    display: "flex", flexWrap: "wrap", gap: 5,
  },
  tsChip: {
    padding: "3px 8px", background: "#0d130d",
    border: "1px solid #1a2a1a",
    color: "#4a6a4a", borderRadius: 4,
    fontFamily: "inherit", fontSize: 10,
    cursor: "pointer", transition: "all .15s",
  },

  // Modal
  modalOverlay: {
    position: "fixed", inset: 0,
    background: "rgba(0,0,0,.85)",
    display: "flex", alignItems: "center",
    justifyContent: "center", zIndex: 999,
  },
  modalBox: {
    position: "relative", maxWidth: "80vw",
    background: "#0d130d", borderRadius: 12,
    padding: 20, border: "1px solid #1a2a1a",
  },
  modalClose: {
    position: "absolute", top: 10, right: 12,
    background: "transparent", border: "none",
    color: "#4a6a4a", fontSize: 18, cursor: "pointer",
  },
};

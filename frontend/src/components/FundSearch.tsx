import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

interface SearchResult {
  fund_code: string;
  short_name: string;
  full_name: string;
  fund_type: string;
}

export default function FundSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);

  // Debounced search
  useEffect(() => {
    if (query.length < 1) {
      setResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const resp = await api.searchFunds(query, 10);
        setResults(resp.data?.funds ?? []);
        setOpen(true);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleSelect = (code: string) => {
    navigate(`/funds/${code}`);
    setQuery("");
    setOpen(false);
  };

  return (
    <div ref={containerRef} style={{ position: "relative", flex: 1, maxWidth: 300 }}>
      <input
        type="text"
        placeholder="搜索基金代码 / 名称..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        style={{
          width: "100%",
          padding: "6px 12px",
          fontSize: 14,
          border: "1px solid var(--color-border)",
          borderRadius: 6,
          background: "var(--color-background)",
          color: "var(--color-text)",
          outline: "none",
        }}
      />
      {open && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            marginTop: 4,
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderRadius: 6,
            boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
            zIndex: 100,
            maxHeight: 320,
            overflowY: "auto",
          }}
        >
          {loading && <div style={{ padding: "8px 12px", color: "var(--color-text-secondary)", fontSize: 13 }}>搜索中...</div>}
          {!loading && results.length === 0 && query.length > 0 && (
            <div style={{ padding: "8px 12px", color: "var(--color-text-secondary)", fontSize: 13 }}>无匹配结果</div>
          )}
          {results.map((r) => (
            <div
              key={r.fund_code}
              onClick={() => handleSelect(r.fund_code)}
              style={{
                padding: "8px 12px",
                cursor: "pointer",
                borderBottom: "1px solid var(--color-border)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--color-background)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "")}
            >
              <span style={{ fontWeight: 600, fontSize: 13, color: "var(--color-primary)" }}>{r.fund_code}</span>
              <span style={{ fontSize: 13, color: "var(--color-text-secondary)", marginLeft: 8, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.short_name || r.full_name}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

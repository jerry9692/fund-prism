/**
 * DataTable — generic sortable data table.
 * Acceptance criterion §4.3: DataTable with sort/filter support.
 */

import { useState, type ReactNode } from "react";

export interface Column<T> {
  key: keyof T | string;
  label: string;
  render?: (row: T) => ReactNode;
  sortable?: boolean;
  className?: string;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  rowKey: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  selectedKey?: string | number;
  emptyMessage?: string;
}

export default function DataTable<T>({
  columns,
  data,
  rowKey,
  onRowClick,
  selectedKey,
  emptyMessage = "暂无数据",
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const sortedData = (() => {
    if (!sortKey) return data;
    const col = columns.find((c) => String(c.key) === sortKey);
    if (!col?.sortable) return data;
    const getVal = (row: T) => {
      if (col.render) return null;
      const v = row[col.key as keyof T];
      return typeof v === "number" || typeof v === "string" ? v : null;
    };
    return [...data].sort((a, b) => {
      const va = getVal(a);
      const vb = getVal(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return sortDir === "asc" ? cmp : -cmp;
    });
  })();

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  if (data.length === 0) {
    return <div className="card empty-state">{emptyMessage}</div>;
  }

  return (
    <div className="card table-card">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={String(col.key)}
                className={col.className}
                style={col.sortable ? { cursor: "pointer", userSelect: "none" } : undefined}
                onClick={() => col.sortable && toggleSort(String(col.key))}
              >
                {col.label}
                {col.sortable && sortKey === String(col.key) && (
                  <span style={{ marginLeft: 4 }}>{sortDir === "asc" ? "↑" : "↓"}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedData.map((row) => {
            const key = rowKey(row);
            return (
              <tr
                key={key}
                className={selectedKey === key ? "selected-row" : ""}
                style={onRowClick ? { cursor: "pointer" } : undefined}
                onClick={() => onRowClick?.(row)}
              >
                {columns.map((col) => (
                  <td key={String(col.key)} className={col.className}>
                    {col.render ? col.render(row) : String(row[col.key as keyof T] ?? "—")}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

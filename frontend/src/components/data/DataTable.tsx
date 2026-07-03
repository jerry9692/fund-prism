// DataTable — 可排序、可点击行的数据表格
// 数字列右对齐 + tabular-nums，hover 行高亮，无外边框

import { useState, useMemo, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  numeric?: boolean;
  sortable?: boolean;
  render?: (row: T) => ReactNode;
  sortValue?: (row: T) => string | number | null;
  width?: string;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  initialSort?: { key: string; order: "asc" | "desc" };
  emptyText?: string;
}

export function DataTable<T>({
  columns,
  data,
  rowKey,
  onRowClick,
  initialSort,
  emptyText = "暂无数据",
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState(initialSort?.key ?? "");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">(
    initialSort?.order ?? "desc"
  );

  const sortedData = useMemo(() => {
    if (!sortKey) return data;
    const col = columns.find((c) => c.key === sortKey);
    if (!col?.sortValue) return data;
    const dir = sortOrder === "asc" ? 1 : -1;
    return [...data].sort((a, b) => {
      const va = col.sortValue!(a);
      const vb = col.sortValue!(b);
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      if (typeof va === "string" && typeof vb === "string") {
        return va.localeCompare(vb) * dir;
      }
      return ((va as number) - (vb as number)) * dir;
    });
  }, [data, sortKey, sortOrder, columns]);

  const handleSort = (col: Column<T>) => {
    if (!col.sortable) return;
    if (sortKey === col.key) {
      setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    } else {
      setSortKey(col.key);
      setSortOrder("desc");
    }
  };

  if (data.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">∅</div>
        <div className="empty-state-title">{emptyText}</div>
      </div>
    );
  }

  return (
    <table className="data-table">
      <thead>
        <tr>
          {columns.map((col) => (
            <th
              key={col.key}
              className={`${col.numeric ? "numeric" : ""} ${
                sortKey === col.key ? "sorted" : ""
              }`}
              style={col.width ? { width: col.width } : undefined}
              onClick={() => handleSort(col)}
            >
              {col.header}
              {col.sortable && (
                <span className="sort-icon">
                  {sortKey === col.key
                    ? sortOrder === "asc"
                      ? "↑"
                      : "↓"
                    : "↕"}
                </span>
              )}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sortedData.map((row) => (
          <tr
            key={rowKey(row)}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
            style={onRowClick ? { cursor: "pointer" } : undefined}
          >
            {columns.map((col) => (
              <td
                key={col.key}
                className={`${col.numeric ? "numeric" : ""} ${
                  !col.render && typeof (row as Record<string, unknown>)[col.key] === "number"
                    ? "mono"
                    : ""
                }`}
              >
                {col.render
                  ? col.render(row)
                  : String((row as Record<string, unknown>)[col.key] ?? "—")}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

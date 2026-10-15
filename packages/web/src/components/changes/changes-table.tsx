"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { ResponsiveTable, type ResponsiveColumn } from "@repowise-dev/ui/shared/responsive-table";
import { formatDate } from "@repowise-dev/ui/lib/format";
import type { ChangeEvidenceSummary, ChangeListItem } from "@/lib/api/changes";
import { categoryLabel, changeLabel } from "@/lib/changes";

/**
 * The kept checklist in one cell: attention first, then unknown, quiet when
 * every item checked out. A checklist with no items reads as unknown, never
 * as clean. The list never builds a checklist; the change page does.
 */
function EvidenceCell({ summary }: { summary: ChangeEvidenceSummary | null | undefined }) {
  const t = useTranslations("views.changes");
  if (!summary) {
    return (
      <span className="text-xs text-[var(--color-text-tertiary)]" title={t("evidenceNotBuiltHint")}>
        {t("evidenceNotBuilt")}
      </span>
    );
  }
  if (summary.ok + summary.attention + summary.unknown === 0) {
    return <span className="text-xs text-[var(--color-text-tertiary)]">{t("unknown")}</span>;
  }
  if (summary.attention === 0 && summary.unknown === 0) {
    return <span className="text-xs text-[var(--color-text-tertiary)]">{t("evidenceClear")}</span>;
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 text-xs">
      {summary.attention > 0 && (
        <span className="inline-flex items-center gap-1.5 text-[var(--color-text-primary)]">
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[var(--color-warning)]" />
          {t("evidenceAttention", { count: summary.attention })}
        </span>
      )}
      {summary.unknown > 0 && (
        <span className="text-[var(--color-text-tertiary)]">
          {t("evidenceUnknown", { count: summary.unknown })}
        </span>
      )}
    </span>
  );
}

/** Merged changes, one row each, linking to the change's page and checklist. */
export function ChangesTable({
  repoId,
  rows,
  showProvenance,
}: {
  repoId: string;
  rows: ChangeListItem[];
  showProvenance: boolean;
}) {
  const t = useTranslations("views.changes");
  const columns: ResponsiveColumn<ChangeListItem>[] = [
    {
      key: "id",
      header: t("change"),
      cellClassName: "whitespace-nowrap",
      render: (c) => (
        <Link
          href={`/repos/${repoId}/changes/${encodeURIComponent(c.id)}`}
          title={c.id}
          className="inline-block max-w-[12rem] truncate whitespace-nowrap align-bottom font-mono text-xs text-[var(--color-accent-primary)] hover:underline"
        >
          {changeLabel(c)}
        </Link>
      ),
    },
    {
      key: "title",
      header: t("title_col"),
      cellClassName: "min-w-[220px] max-w-[440px] truncate",
      render: (c) => <span title={c.title}>{c.title}</span>,
    },
    {
      key: "evidence",
      header: t("evidence"),
      render: (c) => <EvidenceCell summary={c.evidence_summary} />,
    },
    {
      key: "merged_at",
      header: t("merged"),
      priority: 2,
      render: (c) => (
        <span className="text-xs text-[var(--color-text-secondary)]">
          {c.merged_at ? formatDate(c.merged_at) : ""}
        </span>
      ),
    },
    {
      key: "category",
      header: t("category"),
      priority: 2,
      render: (c) => <span className="text-xs">{categoryLabel(t, c.category)}</span>,
    },
    {
      key: "commits",
      header: t("commits"),
      align: "right",
      priority: 3,
      render: (c) => <span className="font-mono text-xs tabular-nums">{c.commit_count}</span>,
    },
    {
      key: "files",
      header: t("files"),
      align: "right",
      priority: 3,
      render: (c) => <span className="font-mono text-xs tabular-nums">{c.files_changed}</span>,
    },
    {
      key: "lines",
      header: t("lines"),
      align: "right",
      priority: 3,
      render: (c) => (
        <span className="font-mono text-xs tabular-nums">
          <span className="text-[var(--color-success)]">+{c.lines_added}</span>{" "}
          <span className="text-[var(--color-error)]">-{c.lines_deleted}</span>
        </span>
      ),
    },
  ];
  if (showProvenance) {
    columns.push({
      key: "provenance",
      header: t("provenance"),
      priority: 3,
      render: (c) => {
        const prov = c.provenance;
        if (!prov) return null;
        const pct = prov.coverage == null ? null : Math.round(prov.coverage * 100);
        return (
          <span className="text-xs">
            {prov.label.replace("_", " ")}
            {pct != null && (
              <span className="text-[var(--color-text-tertiary)]"> · {t("coverage", { pct })}</span>
            )}
          </span>
        );
      },
    });
  }
  return <ResponsiveTable columns={columns} rows={rows} rowKey={(c) => c.id} stacked="sm" />;
}

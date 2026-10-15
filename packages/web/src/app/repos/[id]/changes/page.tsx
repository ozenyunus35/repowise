import { redirect } from "next/navigation";
import { byChangeHref } from "@/lib/changes";

/**
 * The change list lives on the Commits page, grouped by change. Old links keep
 * their category, page and attention filter (`?attention=1` or the API's
 * `?needs_attention=true`).
 */
export default async function ChangesPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ category?: string; offset?: string; attention?: string; needs_attention?: string }>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const offset = Math.max(0, Number.parseInt(sp.offset ?? "0", 10) || 0);
  const attention = sp.attention === "1" || sp.needs_attention === "true" || sp.needs_attention === "1";
  redirect(byChangeHref(id, { category: sp.category, attention, offset }));
}

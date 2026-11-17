import { proxyAdminHls } from "@/lib/live-hls-proxy";

type Props = { params: Promise<{ id: string; path: string[] }> };

export async function GET(_request: Request, { params }: Props) {
  const { id, path } = await params;
  return proxyAdminHls(id, path.join("/"));
}

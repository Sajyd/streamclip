import { proxyUserHls } from "@/lib/live-hls-proxy";

type Props = { params: Promise<{ path: string[] }> };

export async function GET(_request: Request, { params }: Props) {
  const { path } = await params;
  return proxyUserHls(path.join("/"));
}

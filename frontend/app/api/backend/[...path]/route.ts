import { NextRequest } from "next/server";

const internalApiBaseUrl =
  process.env.INTERNAL_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  context: {
    params: Promise<{
      path: string[];
    }>;
  },
) {
  const { path } = await context.params;
  const targetPath = path.join("/");
  const search = request.nextUrl.search;
  const targetUrl = `${internalApiBaseUrl}/${targetPath}${search}`;

  try {
    const response = await fetch(targetUrl, {
      cache: "no-store",
      headers: {
        accept: request.headers.get("accept") ?? "application/json",
      },
    });

    return new Response(response.body, {
      status: response.status,
      headers: {
        "content-type":
          response.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (error) {
    console.error("Backend proxy request failed", {
      error,
      targetUrl,
    });

    return Response.json(
      {
        detail: "We could not reach the backend.",
      },
      { status: 502 },
    );
  }
}

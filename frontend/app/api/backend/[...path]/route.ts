import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(
  request: NextRequest,
  context: {
    params: Promise<{
      path: string[];
    }>;
  },
) {
  return proxyBackendRequest(request, context, { method: "GET" });
}

export async function POST(
  request: NextRequest,
  context: {
    params: Promise<{
      path: string[];
    }>;
  },
) {
  return proxyBackendRequest(request, context, {
    method: "POST",
    body: await request.text(),
  });
}

async function proxyBackendRequest(
  request: NextRequest,
  context: {
    params: Promise<{
      path: string[];
    }>;
  },
  init: {
    method: "GET" | "POST";
    body?: string;
  },
) {
  const { path } = await context.params;
  const targetPath = path.join("/");
  const search = request.nextUrl.search;
  const apiBaseUrl = resolveBackendApiBaseUrl("backend-proxy");
  if (!apiBaseUrl) {
    return Response.json(
      {
        detail: "Backend API URL is not configured.",
      },
      { status: 502 },
    );
  }

  const targetUrl = `${apiBaseUrl}/${targetPath}${search}`;

  try {
    const headers: HeadersInit = {
      accept: request.headers.get("accept") ?? "application/json",
    };
    const contentType = request.headers.get("content-type");
    if (contentType) {
      headers["content-type"] = contentType;
    }

    const response = await fetch(targetUrl, {
      method: init.method,
      body: init.body,
      cache: "no-store",
      headers,
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

function resolveBackendApiBaseUrl(caller: string): string | null {
  const publicApiBaseUrl = normalizeApiBaseUrl(process.env.NEXT_PUBLIC_API_URL);
  const internalApiBaseUrl = normalizeApiBaseUrl(process.env.INTERNAL_API_URL);

  if (publicApiBaseUrl && !isLocalhostUrl(publicApiBaseUrl)) {
    return publicApiBaseUrl;
  }
  if (internalApiBaseUrl) {
    return internalApiBaseUrl;
  }
  if (publicApiBaseUrl) {
    return publicApiBaseUrl;
  }
  if (process.env.NODE_ENV !== "production") {
    return "http://localhost:8000";
  }

  console.error("[backend-proxy] backend API URL is not configured", {
    caller,
    expectedEnv: "NEXT_PUBLIC_API_URL",
  });
  return null;
}

function normalizeApiBaseUrl(value: string | undefined): string | null {
  const normalized = value?.trim().replace(/\/+$/, "");
  return normalized || null;
}

function isLocalhostUrl(value: string): boolean {
  try {
    const hostname = new URL(value).hostname;
    return hostname === "localhost" || hostname === "127.0.0.1";
  } catch {
    return false;
  }
}

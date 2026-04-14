import type {
  AnalysisAccepted,
  AnalysisCreateInput,
  AnalysisResult,
  ErrorEnvelope,
  RepositoryCreateInput,
  RepositoryRead,
} from "./types";

class ApiClientError extends Error {
  code: string;
  details: Record<string, unknown>;
  requestId: string | null;

  constructor(message: string, code = "HTTP_ERROR", details: Record<string, unknown> = {}, requestId: string | null = null) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    throw await toApiClientError(response);
  }

  return (await response.json()) as T;
}

async function requestText(path: string, init?: RequestInit): Promise<string> {
  const response = await fetch(`${apiBase}${path}`, init);
  if (!response.ok) {
    throw await toApiClientError(response);
  }
  return response.text();
}

async function toApiClientError(response: Response): Promise<ApiClientError> {
  const requestId = response.headers.get("X-Request-ID");
  const fallbackMessage = `Request failed with status ${response.status}`;

  try {
    const payload = (await response.json()) as ErrorEnvelope;
    if (payload?.error) {
      return new ApiClientError(
        payload.error.message,
        payload.error.code,
        payload.error.details ?? {},
        payload.error.request_id ?? requestId,
      );
    }
  } catch {
    return new ApiClientError(fallbackMessage, "HTTP_ERROR", {}, requestId);
  }

  return new ApiClientError(fallbackMessage, "HTTP_ERROR", {}, requestId);
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed.";
}

export async function getHealth(): Promise<{ status: string }> {
  return requestJson<{ status: string }>("/api/v1/health");
}

export async function createRepository(input: RepositoryCreateInput): Promise<RepositoryRead> {
  return requestJson<RepositoryRead>("/api/v1/repositories", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function createAnalysis(input: AnalysisCreateInput): Promise<AnalysisAccepted> {
  return requestJson<AnalysisAccepted>("/api/v1/analyses", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function getAnalysis(analysisId: string): Promise<AnalysisResult> {
  return requestJson<AnalysisResult>(`/api/v1/analyses/${analysisId}`);
}

export async function getAnalysisReport(analysisId: string): Promise<string> {
  return requestText(`/api/v1/analyses/${analysisId}/report`);
}

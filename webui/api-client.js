"use strict";

export class ApiError extends Error {
  constructor(message, { status = 0, code = "request_failed" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    throw new ApiError(`Cannot reach the Animatorio server: ${error.message}`);
  }
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.blob();
  if (!response.ok) {
    throw new ApiError(payload?.error || response.statusText || "Request failed", {
      status: response.status,
      code: payload?.code,
    });
  }
  return payload;
}

function post(path, body = {}) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const api = Object.freeze({
  getAsset: () => request("/api/asset"),
  getSourceImage: () => request("/api/source_image"),
  browse: (kind, path) => {
    const query = new URLSearchParams({ kind });
    if (path) query.set("path", path);
    return request(`/api/browse?${query}`);
  },
  preview: (input) => post("/api/preview", input),
  exportGif: (input) => post("/api/export_gif", input),
  save: (input) => post("/api/save", input),
  regenerate: () => post("/api/regenerate"),
  reload: () => post("/api/reload"),
  openAssetFile: (path) => post("/api/open_asset_file", { path }),
  openAssetFromImage: (input) => post("/api/open_asset_from_image", input),
});

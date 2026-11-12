async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) {
    const detail = payload?.detail ?? payload;
    const error = new Error(
      Array.isArray(detail?.errors)
        ? detail.errors.join("；")
        : typeof detail === "string"
          ? detail
          : `请求失败（HTTP ${response.status}）`,
    );
    error.detail = detail;
    error.status = response.status;
    throw error;
  }
  return payload;
}

export const api = {
  bootstrap: () => request("/api/bootstrap"),
  validate: (rules) =>
    request("/api/rules/validate", {
      method: "POST",
      body: JSON.stringify({ rules }),
    }),
  preview: (rules, limit) =>
    request("/api/preview", {
      method: "POST",
      body: JSON.stringify({ rules, limit }),
    }),
  generate: (rules) =>
    request("/api/generate", {
      method: "POST",
      body: JSON.stringify({ rules }),
    }),
  jobs: () => request("/api/jobs"),
  job: (jobId) => request(`/api/jobs/${jobId}`),
};

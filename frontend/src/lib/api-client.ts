import ky from "ky"

export const api = ky.create({
  prefixUrl: "/api/v1",
  hooks: {
    beforeRequest: [
      (request) => {
        try {
          const apiKey = localStorage.getItem("api-key")
          if (apiKey) {
            request.headers.set("X-API-Key", apiKey)
          }
        } catch {
          // localStorage may be unavailable (e.g. Safari private mode)
        }
      },
    ],
  },
})

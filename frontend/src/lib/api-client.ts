import ky from "ky"

export const api = ky.create({
  prefixUrl: "/api_vendors/v1",
  hooks: {
    beforeRequest: [
      (request) => {
        try {
          const apiKey = localStorage.getItem("cadprice-api_vendors-key")
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

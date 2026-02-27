import ky from "ky"

export const api = ky.create({
  prefixUrl: "/api/v1",
  hooks: {
    beforeRequest: [
      (request) => {
        const apiKey = localStorage.getItem("cadprice-api-key")
        if (apiKey) {
          request.headers.set("X-API-Key", apiKey)
        }
      },
    ],
  },
})

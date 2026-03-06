import { createFileRoute } from "@tanstack/react-router"
import { z } from "zod"

const searchSchema = z.object({
  token: z.string().catch(""),
})

export const Route = createFileRoute("/accept-invitation")({
  validateSearch: searchSchema,
})

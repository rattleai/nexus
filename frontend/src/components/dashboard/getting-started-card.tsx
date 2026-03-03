import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"

export function GettingStartedCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Getting Started</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-gray-600 mt-2">
          CADPrice is a manufacturing intelligence platform for STEP file analysis, costing, and 2D
          drawing generation. Use the API to submit jobs and retrieve results.
        </p>
      </CardContent>
    </Card>
  )
}

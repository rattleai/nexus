import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"

export function GettingStartedCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Getting Started</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-gray-600 mt-2">
          Welcome to your multi-tenant SaaS platform. Use the dashboard to monitor service health
          and manage your application.
        </p>
      </CardContent>
    </Card>
  )
}

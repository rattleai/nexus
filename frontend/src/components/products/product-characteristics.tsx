import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Plus, Trash2, GripVertical } from "lucide-react"
import {
  useCharacteristicAssignments,
  useCharacteristics,
  useAssignCharacteristic,
  useRemoveAssignment,
} from "@/hooks/use-characteristics"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/empty-state"

// ── Types ───────────────────────────────────────────────

interface ProductCharacteristicsProps {
  productId: string
}

// ── Char type badge mapping ─────────────────────────────

const charTypeVariant: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  enum: "default",
  numeric: "secondary",
  boolean: "outline",
  text: "destructive",
}

// ── Component ───────────────────────────────────────────

export function ProductCharacteristics({ productId }: ProductCharacteristicsProps) {
  const { t } = useTranslation()
  const { data: assignmentsData, isLoading: loadingAssignments } =
    useCharacteristicAssignments(productId)
  const { data: allCharsData, isLoading: loadingChars } = useCharacteristics()
  const assignCharacteristic = useAssignCharacteristic()
  const removeAssignment = useRemoveAssignment()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [selectedCharId, setSelectedCharId] = useState<string>("")

  const assignedChars = assignmentsData?.items ?? []
  const allChars = allCharsData?.items ?? []

  // Filter out already-assigned characteristics
  const assignedIds = new Set(assignedChars.map((c) => c.id))
  const availableChars = allChars.filter((c) => !assignedIds.has(c.id))

  function handleAssign() {
    if (!selectedCharId) return
    assignCharacteristic.mutate(
      { product_id: productId, characteristic_id: selectedCharId },
      {
        onSuccess: () => {
          setDialogOpen(false)
          setSelectedCharId("")
        },
      },
    )
  }

  if (loadingAssignments || loadingChars) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-80" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div className="space-y-1.5">
          <CardTitle>{t("products.characteristics", "Characteristics")}</CardTitle>
          <CardDescription>
            {t(
              "products.characteristicsDescription",
              "Manage the characteristics assigned to this product.",
            )}
          </CardDescription>
        </div>

        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <Plus className="mr-2 h-4 w-4" />
              {t("products.addCharacteristic", "Add Characteristic")}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>
                {t("products.assignCharacteristic", "Assign Characteristic")}
              </DialogTitle>
              <DialogDescription>
                {t(
                  "products.assignCharacteristicDescription",
                  "Select a characteristic to assign to this product.",
                )}
              </DialogDescription>
            </DialogHeader>

            <Select value={selectedCharId} onValueChange={setSelectedCharId}>
              <SelectTrigger>
                <SelectValue
                  placeholder={t(
                    "products.selectCharacteristic",
                    "Select characteristic...",
                  )}
                />
              </SelectTrigger>
              <SelectContent>
                {availableChars.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name} ({c.char_type})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <DialogFooter>
              <Button
                onClick={handleAssign}
                disabled={!selectedCharId || assignCharacteristic.isPending}
              >
                {assignCharacteristic.isPending
                  ? t("common.assigning", "Assigning...")
                  : t("common.assign", "Assign")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardHeader>

      <CardContent>
        {assignedChars.length === 0 ? (
          <EmptyState
            title={t("products.noCharacteristics", "No characteristics assigned")}
            description={t(
              "products.noCharacteristicsDescription",
              "Assign characteristics to define what can be configured on this product.",
            )}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>{t("common.name", "Name")}</TableHead>
                <TableHead>{t("characteristics.type", "Type")}</TableHead>
                <TableHead>{t("characteristics.required", "Required")}</TableHead>
                <TableHead>{t("characteristics.values", "Values")}</TableHead>
                <TableHead className="w-16" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {assignedChars.map((char) => (
                <TableRow key={char.id}>
                  <TableCell>
                    <GripVertical className="h-4 w-4 text-muted-foreground cursor-grab" />
                  </TableCell>
                  <TableCell className="font-medium">{char.name}</TableCell>
                  <TableCell>
                    <Badge variant={charTypeVariant[char.char_type] ?? "secondary"}>
                      {char.char_type}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={char.is_required ? "default" : "outline"}>
                      {char.is_required
                        ? t("common.yes", "Yes")
                        : t("common.no", "No")}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {char.char_type === "enum"
                      ? `${char.values?.length ?? 0} values`
                      : char.char_type === "numeric"
                        ? `${char.numeric_min ?? "–"} to ${char.numeric_max ?? "–"}`
                        : "—"}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() =>
                        removeAssignment.mutate({
                          assignmentId: char.id,
                          productId,
                        })
                      }
                      disabled={removeAssignment.isPending}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

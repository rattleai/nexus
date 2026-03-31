import { useState, useEffect } from "react"
import { useForm, useFieldArray } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Plus, Pencil, Trash2, Table2 } from "lucide-react"
import {
  useVariantTables,
  useCreateVariantTable,
  useUpdateVariantTable,
  useDeleteVariantTable,
} from "@/apps/cpq/hooks/use-constraints"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/empty-state"
import { ConfirmDialog } from "@/components/confirm-dialog"
import type { VariantTable } from "@/apps/cpq/types/configurator"

// ── Types ───────────────────────────────────────────────

interface ProductVariantTablesProps {
  productId: string
}

// ── Form Schema ─────────────────────────────────────────

const columnSchema = z.object({
  name: z.string().min(1, "Column name is required"),
  type: z.enum(["input", "output"]),
})

const variantTableFormSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().nullable().optional(),
  columns: z.array(columnSchema).min(1, "At least one column required"),
  rows: z.array(z.record(z.string())),
})

type VariantTableFormValues = z.infer<typeof variantTableFormSchema>

// ── Form Dialog ─────────────────────────────────────────

function VariantTableFormDialog({
  productId,
  table,
  open,
  onOpenChange,
}: {
  productId: string
  table?: VariantTable | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const createTable = useCreateVariantTable()
  const updateTable = useUpdateVariantTable()
  const isEditing = !!table

  // Parse existing table data into form-friendly format
  function parseTableColumns(t: VariantTable) {
    const cols: { name: string; type: "input" | "output" }[] = []
    const inputSet = new Set(t.input_columns ?? [])
    const outputSet = new Set(t.output_columns ?? [])

    // Reconstruct from columns array if available
    if (t.columns && t.columns.length > 0) {
      for (const col of t.columns) {
        const colName = (col as Record<string, string>).name ?? ""
        const colType = inputSet.has(colName)
          ? "input"
          : outputSet.has(colName)
            ? "output"
            : ((col as Record<string, string>).type === "output" ? "output" : "input")
        cols.push({ name: colName, type: colType })
      }
    } else {
      // Fallback: derive from input_columns and output_columns
      for (const name of t.input_columns ?? []) {
        cols.push({ name, type: "input" })
      }
      for (const name of t.output_columns ?? []) {
        cols.push({ name, type: "output" })
      }
    }

    return cols
  }

  function parseTableRows(t: VariantTable) {
    return (t.rows ?? []).map((row) => {
      const r: Record<string, string> = {}
      for (const [k, v] of Object.entries(row)) {
        r[k] = String(v ?? "")
      }
      return r
    })
  }

  const form = useForm<VariantTableFormValues>({
    resolver: zodResolver(variantTableFormSchema),
    defaultValues: {
      name: "",
      description: "",
      columns: [{ name: "", type: "input" }],
      rows: [],
    },
  })

  const {
    fields: columnFields,
    append: appendColumn,
    remove: removeColumn,
  } = useFieldArray({
    control: form.control,
    name: "columns",
  })

  const watchColumns = form.watch("columns")
  const watchRows = form.watch("rows")

  useEffect(() => {
    if (open) {
      if (isEditing && table) {
        const cols = parseTableColumns(table)
        const rows = parseTableRows(table)
        form.reset({
          name: table.name,
          description: table.description ?? "",
          columns: cols.length > 0 ? cols : [{ name: "", type: "input" }],
          rows,
        })
      } else {
        form.reset({
          name: "",
          description: "",
          columns: [{ name: "", type: "input" }],
          rows: [],
        })
      }
    }
  }, [open, table, isEditing, form])

  function handleAddRow() {
    const newRow: Record<string, string> = {}
    for (const col of watchColumns) {
      if (col.name) {
        newRow[col.name] = ""
      }
    }
    form.setValue("rows", [...watchRows, newRow])
  }

  function handleRemoveRow(index: number) {
    const updated = [...watchRows]
    updated.splice(index, 1)
    form.setValue("rows", updated)
  }

  function handleCellChange(rowIndex: number, colName: string, value: string) {
    const updated = [...watchRows]
    updated[rowIndex] = { ...updated[rowIndex], [colName]: value }
    form.setValue("rows", updated)
  }

  function onSubmit(values: VariantTableFormValues) {
    const inputColumns = values.columns
      .filter((c) => c.type === "input")
      .map((c) => c.name)
    const outputColumns = values.columns
      .filter((c) => c.type === "output")
      .map((c) => c.name)
    const columns = values.columns.map((c) => ({ name: c.name, type: c.type }))

    // Ensure rows only contain keys matching current column names
    const validColNames = new Set(values.columns.map((c) => c.name))
    const rows = values.rows.map((row) => {
      const cleaned: Record<string, string> = {}
      for (const [k, v] of Object.entries(row)) {
        if (validColNames.has(k)) {
          cleaned[k] = v
        }
      }
      // Also ensure all column keys exist
      for (const name of validColNames) {
        if (!(name in cleaned)) {
          cleaned[name] = ""
        }
      }
      return cleaned
    })

    if (isEditing && table) {
      updateTable.mutate(
        {
          id: table.id,
          data: {
            name: values.name,
            description: values.description || null,
            columns,
            rows,
            input_columns: inputColumns,
            output_columns: outputColumns,
          },
        },
        { onSuccess: () => { onOpenChange(false); form.reset() } },
      )
    } else {
      createTable.mutate(
        {
          product_id: productId,
          name: values.name,
          description: values.description || null,
          columns,
          rows,
          input_columns: inputColumns,
          output_columns: outputColumns,
        },
        { onSuccess: () => { onOpenChange(false); form.reset() } },
      )
    }
  }

  const isPending = isEditing ? updateTable.isPending : createTable.isPending
  const validColumns = watchColumns.filter((c) => c.name.trim() !== "")

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEditing ? "Edit Variant Table" : "Create Variant Table"}
          </DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the variant table definition and data."
              : "Define a new lookup table with input and output columns."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
            {/* Basic Fields */}
            <div className="grid grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input {...field} placeholder="e.g. Engine-Transmission Mapping" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description</FormLabel>
                    <FormControl>
                      <Textarea
                        {...field}
                        value={field.value ?? ""}
                        rows={1}
                        placeholder="Optional description..."
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            {/* Column Definitions */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-semibold">Column Definitions</h4>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => appendColumn({ name: "", type: "input" })}
                >
                  <Plus className="mr-1.5 h-3.5 w-3.5" />
                  Add Column
                </Button>
              </div>

              <FormField
                control={form.control}
                name="columns"
                render={() => (
                  <FormItem>
                    <FormMessage />
                    <div className="space-y-2">
                      {columnFields.map((field, index) => (
                        <div key={field.id} className="flex items-center gap-2">
                          <FormField
                            control={form.control}
                            name={`columns.${index}.name`}
                            render={({ field: nameField }) => (
                              <FormItem className="flex-1">
                                <FormControl>
                                  <Input
                                    {...nameField}
                                    placeholder="Column name"
                                  />
                                </FormControl>
                                <FormMessage />
                              </FormItem>
                            )}
                          />

                          <FormField
                            control={form.control}
                            name={`columns.${index}.type`}
                            render={({ field: typeField }) => (
                              <FormItem className="w-32">
                                <Select
                                  onValueChange={typeField.onChange}
                                  value={typeField.value}
                                >
                                  <FormControl>
                                    <SelectTrigger>
                                      <SelectValue />
                                    </SelectTrigger>
                                  </FormControl>
                                  <SelectContent>
                                    <SelectItem value="input">Input</SelectItem>
                                    <SelectItem value="output">Output</SelectItem>
                                  </SelectContent>
                                </Select>
                              </FormItem>
                            )}
                          />

                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 shrink-0 text-destructive"
                            disabled={columnFields.length <= 1}
                            onClick={() => removeColumn(index)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </FormItem>
                )}
              />
            </div>

            {/* Row Data */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-semibold">
                  Row Data
                  {watchRows.length > 0 && (
                    <span className="ml-2 text-xs font-normal text-muted-foreground">
                      ({watchRows.length} row{watchRows.length !== 1 ? "s" : ""})
                    </span>
                  )}
                </h4>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleAddRow}
                  disabled={validColumns.length === 0}
                >
                  <Plus className="mr-1.5 h-3.5 w-3.5" />
                  Add Row
                </Button>
              </div>

              {validColumns.length === 0 ? (
                <p className="text-sm text-muted-foreground italic py-4 text-center">
                  Define at least one column with a name to add rows.
                </p>
              ) : watchRows.length === 0 ? (
                <p className="text-sm text-muted-foreground italic py-4 text-center">
                  No rows yet. Click "Add Row" to start adding data.
                </p>
              ) : (
                <div className="rounded-md border max-h-[300px] overflow-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        {validColumns.map((col) => (
                          <TableHead key={col.name} className="text-xs whitespace-nowrap">
                            {col.name}
                            <Badge
                              variant="outline"
                              className="ml-1.5 text-[10px] px-1 py-0"
                            >
                              {col.type}
                            </Badge>
                          </TableHead>
                        ))}
                        <TableHead className="w-10" />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {watchRows.map((row, rowIdx) => (
                        <TableRow key={rowIdx}>
                          {validColumns.map((col) => (
                            <TableCell key={col.name} className="p-1">
                              <Input
                                value={row[col.name] ?? ""}
                                onChange={(e) =>
                                  handleCellChange(rowIdx, col.name, e.target.value)
                                }
                                className="h-8 text-xs"
                              />
                            </TableCell>
                          ))}
                          <TableCell className="p-1">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-destructive"
                              onClick={() => handleRemoveRow(rowIdx)}
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>

            <DialogFooter>
              <Button variant="outline" type="button" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending ? "Saving..." : isEditing ? "Update" : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

// ── Main Component ──────────────────────────────────────

export function ProductVariantTables({ productId }: ProductVariantTablesProps) {
  const { data: tablesData, isLoading } = useVariantTables(productId)
  const deleteTable = useDeleteVariantTable()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingTable, setEditingTable] = useState<VariantTable | null>(null)

  const tables = tablesData?.items ?? []

  function handleNew() {
    setEditingTable(null)
    setDialogOpen(true)
  }

  function handleEdit(table: VariantTable) {
    setEditingTable(table)
    setDialogOpen(true)
  }

  function handleDelete(table: VariantTable) {
    deleteTable.mutate(table.id)
  }

  // Loading state
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-80" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </CardContent>
      </Card>
    )
  }

  // Empty state
  if (tables.length === 0) {
    return (
      <>
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Table2 className="h-5 w-5" />
                Variant Tables
              </CardTitle>
            </div>
            <CardDescription>
              Lookup tables used by table-type constraints to map input values to outputs.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <EmptyState
              icon={Table2}
              title="No variant tables yet"
              description="Create a variant table to define spreadsheet-like lookup data for table constraints."
              action={
                <Button onClick={handleNew}>
                  <Plus className="mr-1.5 h-4 w-4" />
                  New Table
                </Button>
              }
            />
          </CardContent>
        </Card>

        <VariantTableFormDialog
          productId={productId}
          table={editingTable}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
        />
      </>
    )
  }

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Table2 className="h-5 w-5" />
                Variant Tables
              </CardTitle>
              <CardDescription className="mt-1">
                Lookup tables used by table-type constraints to map input values to outputs.
              </CardDescription>
            </div>
            <Button size="sm" onClick={handleNew}>
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              New Table
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="text-center">Columns</TableHead>
                <TableHead className="text-center">Rows</TableHead>
                <TableHead>Input Columns</TableHead>
                <TableHead>Output Columns</TableHead>
                <TableHead className="w-24 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tables.map((table) => (
                <TableRow key={table.id}>
                  <TableCell className="font-medium">{table.name}</TableCell>
                  <TableCell className="text-muted-foreground text-sm max-w-[200px] truncate">
                    {table.description || "—"}
                  </TableCell>
                  <TableCell className="text-center">
                    {(table.columns ?? []).length}
                  </TableCell>
                  <TableCell className="text-center">
                    {(table.rows ?? []).length}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {(table.input_columns ?? []).map((col) => (
                        <Badge key={col} variant="outline" className="text-xs">
                          {col}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {(table.output_columns ?? []).map((col) => (
                        <Badge
                          key={col}
                          className="text-xs bg-cyan-600 hover:bg-cyan-600 text-white"
                        >
                          {col}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => handleEdit(table)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <ConfirmDialog
                        title="Delete Variant Table"
                        description={`Are you sure you want to delete "${table.name}"? Any constraint rules referencing this table will need to be updated.`}
                        confirmLabel="Delete"
                        variant="destructive"
                        onConfirm={() => handleDelete(table)}
                      >
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-destructive"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </ConfirmDialog>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <VariantTableFormDialog
        productId={productId}
        table={editingTable}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
      />
    </>
  )
}

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { ScrollArea } from "@/components/ui/scroll-area"
import { BOMItemForm } from "./bom-item-form"
import type { BOMItem, Characteristic } from "@/types/configurator"

interface BOMItemSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  bomId: string
  productId: string
  editItem?: BOMItem | null
  parentItemId?: string | null
  allItems: BOMItem[]
  characteristics: Characteristic[]
}

export function BOMItemSheet({
  open,
  onOpenChange,
  bomId,
  productId,
  editItem,
  parentItemId,
  allItems,
  characteristics,
}: BOMItemSheetProps) {
  const isEditing = !!editItem

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>
            {isEditing ? `Edit: ${editItem.part_number}` : "Add Item"}
          </SheetTitle>
          <SheetDescription>
            {isEditing
              ? "Update the BOM item details and selection conditions."
              : "Add a new item to the bill of materials."}
          </SheetDescription>
        </SheetHeader>
        <ScrollArea className="h-[calc(100vh-8rem)] pr-4 mt-4">
          <BOMItemForm
            bomId={bomId}
            productId={productId}
            editItem={editItem}
            parentItemId={parentItemId}
            allItems={allItems}
            characteristics={characteristics}
            onSuccess={() => onOpenChange(false)}
            onCancel={() => onOpenChange(false)}
          />
        </ScrollArea>
      </SheetContent>
    </Sheet>
  )
}

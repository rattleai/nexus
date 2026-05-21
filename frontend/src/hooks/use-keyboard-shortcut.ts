import { useHotkeys, type Options } from "react-hotkeys-hook"
import type { RefObject } from "react"

type HotkeyCallback = (e: KeyboardEvent) => void

export function useKeyboardShortcut(
  keys: string,
  callback: HotkeyCallback,
  options?: Options & { ref?: RefObject<HTMLElement | null> },
) {
  const { ref, ...hotkeyOptions } = options ?? {}
  return useHotkeys(
    keys,
    (e) => {
      e.preventDefault()
      callback(e)
    },
    {
      enableOnFormTags: false,
      ...hotkeyOptions,
    },
    ref ? [ref] : undefined,
  )
}

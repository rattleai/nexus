import { cn } from "@/lib/utils"

interface ResponsiveImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string
  alt: string
  widths?: number[]
  aspectRatio?: string
  /** Base path for image transform URL generation (e.g. CDN transform prefix) */
  transformPrefix?: string
}

function buildSrcSet(src: string, widths: number[], transformPrefix?: string): string {
  if (transformPrefix) {
    return widths
      .map((w) => `${transformPrefix}width=${w},format=auto/${src} ${w}w`)
      .join(", ")
  }
  return widths.map((w) => `${src} ${w}w`).join(", ")
}

/**
 * Responsive image component with lazy loading, aspect ratio container,
 * and optional CDN image transform URL generation.
 */
export function ResponsiveImage({
  src,
  alt,
  widths = [320, 640, 960, 1280],
  aspectRatio = "16/9",
  transformPrefix,
  className,
  ...props
}: ResponsiveImageProps) {
  const srcSet = buildSrcSet(src, widths, transformPrefix)
  const sizes = "(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw"

  return (
    <div className={cn("overflow-hidden", className)} style={{ aspectRatio }}>
      <img
        src={src}
        srcSet={srcSet}
        sizes={sizes}
        alt={alt}
        loading="lazy"
        decoding="async"
        className="h-full w-full object-cover"
        {...props}
      />
    </div>
  )
}

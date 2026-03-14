import * as React from "react"
import { useTranslation } from "react-i18next"
import { Pause, Play, Volume2, VolumeX } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"

interface AudioPlayerProps {
  src: string
  title?: string
  className?: string
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00"
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, "0")}`
}

export function AudioPlayer({ src, title, className }: AudioPlayerProps) {
  const { t } = useTranslation()
  const audioRef = React.useRef<HTMLAudioElement>(null)
  const [isPlaying, setIsPlaying] = React.useState(false)
  const [currentTime, setCurrentTime] = React.useState(0)
  const [duration, setDuration] = React.useState(0)
  const [volume, setVolume] = React.useState(1)
  const [isMuted, setIsMuted] = React.useState(false)
  const [isLoaded, setIsLoaded] = React.useState(false)

  React.useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    const onLoadedMetadata = () => {
      setDuration(audio.duration)
      setIsLoaded(true)
    }
    const onTimeUpdate = () => setCurrentTime(audio.currentTime)
    const onEnded = () => setIsPlaying(false)
    const onPlay = () => setIsPlaying(true)
    const onPause = () => setIsPlaying(false)

    audio.addEventListener("loadedmetadata", onLoadedMetadata)
    audio.addEventListener("timeupdate", onTimeUpdate)
    audio.addEventListener("ended", onEnded)
    audio.addEventListener("play", onPlay)
    audio.addEventListener("pause", onPause)

    return () => {
      audio.removeEventListener("loadedmetadata", onLoadedMetadata)
      audio.removeEventListener("timeupdate", onTimeUpdate)
      audio.removeEventListener("ended", onEnded)
      audio.removeEventListener("play", onPlay)
      audio.removeEventListener("pause", onPause)
    }
  }, [])

  // Reset state when src changes
  React.useEffect(() => {
    setIsPlaying(false)
    setCurrentTime(0)
    setDuration(0)
    setIsLoaded(false)
  }, [src])

  const togglePlay = React.useCallback(() => {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) {
      audio.play()
    } else {
      audio.pause()
    }
  }, [])

  const handleSeek = React.useCallback((value: number[]) => {
    const audio = audioRef.current
    if (!audio) return
    audio.currentTime = value[0]
    setCurrentTime(value[0])
  }, [])

  const handleVolumeChange = React.useCallback((value: number[]) => {
    const audio = audioRef.current
    if (!audio) return
    const newVolume = value[0]
    audio.volume = newVolume
    setVolume(newVolume)
    if (newVolume > 0 && isMuted) {
      audio.muted = false
      setIsMuted(false)
    }
  }, [isMuted])

  const toggleMute = React.useCallback(() => {
    const audio = audioRef.current
    if (!audio) return
    const nextMuted = !isMuted
    audio.muted = nextMuted
    setIsMuted(nextMuted)
  }, [isMuted])

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-xl border bg-card p-4 text-card-foreground shadow-sm",
        className,
      )}
    >
      <audio ref={audioRef} src={src} preload="metadata" />

      {title && (
        <p className="truncate text-sm font-medium">{title}</p>
      )}

      {/* Progress bar */}
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          className="h-9 w-9 shrink-0"
          onClick={togglePlay}
          disabled={!isLoaded}
          aria-label={isPlaying ? t("aria.pause") : t("aria.play")}
        >
          {isPlaying ? (
            <Pause className="h-4 w-4" />
          ) : (
            <Play className="h-4 w-4" />
          )}
        </Button>

        <span className="w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
          {formatTime(currentTime)}
        </span>

        <Slider
          value={[currentTime]}
          min={0}
          max={duration || 1}
          step={0.1}
          onValueChange={handleSeek}
          disabled={!isLoaded}
          className="flex-1"
          aria-label={t("aria.seek")}
        />

        <span className="w-10 shrink-0 text-xs tabular-nums text-muted-foreground">
          {formatTime(duration)}
        </span>

        {/* Volume */}
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0"
            onClick={toggleMute}
            aria-label={isMuted ? t("aria.unmute") : t("aria.mute")}
          >
            {isMuted || volume === 0 ? (
              <VolumeX className="h-4 w-4" />
            ) : (
              <Volume2 className="h-4 w-4" />
            )}
          </Button>
          <Slider
            value={[isMuted ? 0 : volume]}
            min={0}
            max={1}
            step={0.01}
            onValueChange={handleVolumeChange}
            className="w-20"
            aria-label={t("aria.volume")}
          />
        </div>
      </div>
    </div>
  )
}

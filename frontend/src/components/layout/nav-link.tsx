import { Link } from "@tanstack/react-router"
import { cn } from "@/lib/utils"

interface NavLinkProps {
  href: string
  label: string
}

export function NavLink({ href, label }: NavLinkProps) {
  return (
    <Link
      to={href}
      className="text-sm font-medium"
      activeProps={{ className: "text-brand-600" }}
      inactiveProps={{ className: "text-gray-600 hover:text-gray-900" }}
      activeOptions={{ exact: true }}
    >
      {({ isActive }) => (
        <span className={cn(isActive ? "text-brand-600" : "text-gray-600 hover:text-gray-900")}>
          {label}
        </span>
      )}
    </Link>
  )
}

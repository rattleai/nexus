import { Link } from "@tanstack/react-router"

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
      {label}
    </Link>
  )
}

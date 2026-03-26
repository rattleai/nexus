"""Seed a complete product configurator test environment.

Creates a realistic manufacturing scenario with 2 product families, 4 products,
shared and product-specific characteristics, constraint rules, variant tables,
150% super BOMs with selection-conditional items, and pricing rules.

Usage:
    python -m scripts.seed_configurator

Scenario:
    Family: "Industrial Motors" (2 products)
        1. AC Induction Motor  — 5 characteristics, 8 constraints, 12-item BOM
        2. Servo Drive Motor   — 5 characteristics, 6 constraints, 10-item BOM

    Family: "Control Panels" (2 products)
        3. Standard Panel      — 4 characteristics, 5 constraints, 9-item BOM
        4. HMI Touch Panel     — 4 characteristics, 4 constraints, 8-item BOM
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BOMHeader,
    BOMItem,
    BOMItemType,
    Characteristic,
    CharacteristicAssignment,
    CharacteristicGroup,
    CharacteristicType,
    CharacteristicValue,
    ConstraintGroup,
    ConstraintRule,
    ConstraintType,
    PricingRule,
    PricingRuleType,
    Product,
    ProductFamily,
    ProductStatus,
    Tenant,
    VariantTable,
)
from app.db.session import async_session_factory, dispose_engines

TENANT_SLUG = "dev-team"


# ── Helpers ─────────────────────────────────────────────────


def _char_val(tenant_id, char, value, label, order=0, price_adj=None):
    """Shorthand for creating a CharacteristicValue."""
    return CharacteristicValue(
        tenant_id=tenant_id,
        characteristic_id=char.id,
        value=value,
        label=label,
        display_order=order,
        price_adjustment=price_adj,
    )


def _assign(tenant_id, product, char, order=0, required=True, default=None,
            min_sel=None, max_sel=None):
    """Shorthand for creating a CharacteristicAssignment."""
    return CharacteristicAssignment(
        tenant_id=tenant_id,
        product_id=product.id,
        characteristic_id=char.id,
        display_order=order,
        is_required=required,
        default_value=default,
        min_select=min_sel,
        max_select=max_sel,
    )


def _rule(tenant_id, product, group, name, ctype, expression, priority=0):
    """Shorthand for creating a ConstraintRule."""
    return ConstraintRule(
        tenant_id=tenant_id,
        product_id=product.id,
        group_id=group.id,
        name=name,
        constraint_type=ctype,
        expression=expression,
        priority=priority,
        is_active=True,
    )


def _bom_item(tenant_id, header, part_no, part_name, qty=Decimal("1"),
              item_type=BOMItemType.COMPONENT, condition=None,
              qty_expr=None, unit_cost=None, parent=None, sort=0):
    """Shorthand for creating a BOMItem."""
    return BOMItem(
        tenant_id=tenant_id,
        bom_header_id=header.id,
        parent_item_id=parent.id if parent else None,
        item_type=item_type,
        part_number=part_no,
        part_name=part_name,
        quantity=qty,
        quantity_expression=qty_expr,
        unit_of_measure="EA",
        selection_condition=condition,
        unit_cost=unit_cost,
        sort_order=sort,
    )


def _pricing(tenant_id, product, name, rtype, expression, priority=0):
    """Shorthand for creating a PricingRule."""
    return PricingRule(
        tenant_id=tenant_id,
        product_id=product.id,
        name=name,
        rule_type=rtype,
        expression=expression,
        priority=priority,
        is_active=True,
        currency="EUR",
    )


# ── Main seed logic ─────────────────────────────────────────


async def seed(session: AsyncSession) -> None:
    # ── Tenant lookup ───────────────────────────────────────
    result = await session.execute(
        select(Tenant).where(Tenant.slug == TENANT_SLUG)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        tenant = Tenant(name="Dev Team", slug=TENANT_SLUG)
        session.add(tenant)
        await session.flush()
        print(f"  Created tenant: {TENANT_SLUG}")
    tid = tenant.id

    # Check idempotency — skip if data already seeded
    existing = await session.execute(
        select(ProductFamily).where(
            ProductFamily.tenant_id == tid,
            ProductFamily.slug == "industrial-motors",
            ProductFamily.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        print("  Configurator seed data already exists — skipping.")
        return

    # ════════════════════════════════════════════════════════
    # PRODUCT FAMILIES
    # ════════════════════════════════════════════════════════

    fam_motors = ProductFamily(
        tenant_id=tid, name="Industrial Motors", slug="industrial-motors",
        description="Variable-speed industrial motor product line",
    )
    fam_panels = ProductFamily(
        tenant_id=tid, name="Control Panels", slug="control-panels",
        description="Electrical control panel assemblies",
    )
    session.add_all([fam_motors, fam_panels])
    await session.flush()
    print(f"  Created 2 product families")

    # ════════════════════════════════════════════════════════
    # PRODUCTS
    # ════════════════════════════════════════════════════════

    prod_ac = Product(
        tenant_id=tid, family_id=fam_motors.id,
        name="AC Induction Motor", slug="ac-induction-motor",
        description="Three-phase AC induction motor, 0.75–30 kW",
        sku_prefix="ACM", status=ProductStatus.ACTIVE,
    )
    prod_servo = Product(
        tenant_id=tid, family_id=fam_motors.id,
        name="Servo Drive Motor", slug="servo-drive-motor",
        description="High-precision servo motor with encoder feedback",
        sku_prefix="SRV", status=ProductStatus.ACTIVE,
    )
    prod_panel = Product(
        tenant_id=tid, family_id=fam_panels.id,
        name="Standard Control Panel", slug="standard-control-panel",
        description="DIN-rail mounted industrial control panel",
        sku_prefix="SCP", status=ProductStatus.ACTIVE,
    )
    prod_hmi = Product(
        tenant_id=tid, family_id=fam_panels.id,
        name="HMI Touch Panel", slug="hmi-touch-panel",
        description="Touchscreen HMI operator panel with PLC integration",
        sku_prefix="HMI", status=ProductStatus.ACTIVE,
    )
    session.add_all([prod_ac, prod_servo, prod_panel, prod_hmi])
    await session.flush()
    print(f"  Created 4 products")

    # ════════════════════════════════════════════════════════
    # CHARACTERISTIC GROUPS
    # ════════════════════════════════════════════════════════

    grp_electrical = CharacteristicGroup(
        tenant_id=tid, name="Electrical", slug="electrical",
        description="Voltage, phase, and power characteristics", display_order=0,
    )
    grp_mechanical = CharacteristicGroup(
        tenant_id=tid, name="Mechanical", slug="mechanical",
        description="Frame, mounting, and shaft characteristics", display_order=1,
    )
    grp_environment = CharacteristicGroup(
        tenant_id=tid, name="Environment", slug="environment",
        description="IP rating, temperature, and certification", display_order=2,
    )
    grp_interface = CharacteristicGroup(
        tenant_id=tid, name="Interface", slug="interface",
        description="Communication and display characteristics", display_order=3,
    )
    session.add_all([grp_electrical, grp_mechanical, grp_environment, grp_interface])
    await session.flush()
    print(f"  Created 4 characteristic groups")

    # ════════════════════════════════════════════════════════
    # CHARACTERISTICS + VALUES
    # ════════════════════════════════════════════════════════

    # --- voltage (enum, shared across motors) ---
    c_voltage = Characteristic(
        tenant_id=tid, group_id=grp_electrical.id,
        name="Supply Voltage", slug="voltage",
        char_type=CharacteristicType.ENUM, is_required=True,
    )
    session.add(c_voltage)
    await session.flush()
    for i, (v, l) in enumerate([
        ("230v-1ph", "230 V single-phase"),
        ("400v-3ph", "400 V three-phase"),
        ("480v-3ph", "480 V three-phase"),
        ("690v-3ph", "690 V three-phase"),
    ]):
        session.add(_char_val(tid, c_voltage, v, l, i))

    # --- power_rating (numeric, kW) ---
    c_power = Characteristic(
        tenant_id=tid, group_id=grp_electrical.id,
        name="Power Rating", slug="power-rating",
        char_type=CharacteristicType.NUMERIC, is_required=True,
        numeric_min=0.75, numeric_max=30.0, numeric_step=0.25, unit="kW",
    )
    session.add(c_power)

    # --- frame_size (enum) ---
    c_frame = Characteristic(
        tenant_id=tid, group_id=grp_mechanical.id,
        name="Frame Size", slug="frame-size",
        char_type=CharacteristicType.ENUM, is_required=True,
    )
    session.add(c_frame)
    await session.flush()
    for i, (v, l) in enumerate([
        ("71", "IEC 71"), ("80", "IEC 80"), ("90", "IEC 90"),
        ("100", "IEC 100"), ("112", "IEC 112"), ("132", "IEC 132"),
        ("160", "IEC 160"), ("180", "IEC 180"), ("200", "IEC 200"),
    ]):
        session.add(_char_val(tid, c_frame, v, l, i))

    # --- mounting (enum) ---
    c_mounting = Characteristic(
        tenant_id=tid, group_id=grp_mechanical.id,
        name="Mounting Type", slug="mounting",
        char_type=CharacteristicType.ENUM, is_required=True,
    )
    session.add(c_mounting)
    await session.flush()
    for i, (v, l) in enumerate([
        ("b3-foot", "B3 Foot Mount"),
        ("b5-flange", "B5 Flange Mount"),
        ("b14-face", "B14 Face Mount"),
        ("b35-foot-flange", "B35 Foot + Flange"),
    ]):
        session.add(_char_val(tid, c_mounting, v, l, i))

    # --- ip_rating (enum) ---
    c_ip = Characteristic(
        tenant_id=tid, group_id=grp_environment.id,
        name="IP Rating", slug="ip-rating",
        char_type=CharacteristicType.ENUM, is_required=True,
    )
    session.add(c_ip)
    await session.flush()
    for i, (v, l, adj) in enumerate([
        ("ip55", "IP55 (Dust/jet-proof)", None),
        ("ip56", "IP56 (Dust/wave-proof)", Decimal("15.00")),
        ("ip65", "IP65 (Dust-tight/jet-proof)", Decimal("35.00")),
        ("ip66", "IP66 (Dust-tight/wave-proof)", Decimal("55.00")),
    ]):
        session.add(_char_val(tid, c_ip, v, l, i, adj))

    # --- brake (boolean, motors only) ---
    c_brake = Characteristic(
        tenant_id=tid, group_id=grp_mechanical.id,
        name="Integrated Brake", slug="brake",
        char_type=CharacteristicType.BOOLEAN,
    )
    session.add(c_brake)
    await session.flush()
    session.add(_char_val(tid, c_brake, "true", "Yes", 0, Decimal("120.00")))
    session.add(_char_val(tid, c_brake, "false", "No", 1))

    # --- encoder (enum, servo only) ---
    c_encoder = Characteristic(
        tenant_id=tid, group_id=grp_electrical.id,
        name="Encoder Type", slug="encoder",
        char_type=CharacteristicType.ENUM, is_required=True,
    )
    session.add(c_encoder)
    await session.flush()
    for i, (v, l, adj) in enumerate([
        ("incremental-1024", "Incremental 1024 PPR", None),
        ("incremental-4096", "Incremental 4096 PPR", Decimal("45.00")),
        ("absolute-single", "Absolute Single-Turn", Decimal("85.00")),
        ("absolute-multi", "Absolute Multi-Turn", Decimal("140.00")),
    ]):
        session.add(_char_val(tid, c_encoder, v, l, i, adj))

    # --- panel_size (enum, panels only) ---
    c_panel_size = Characteristic(
        tenant_id=tid, group_id=grp_mechanical.id,
        name="Enclosure Size", slug="panel-size",
        char_type=CharacteristicType.ENUM, is_required=True,
    )
    session.add(c_panel_size)
    await session.flush()
    for i, (v, l) in enumerate([
        ("small", "400x300x200 mm"),
        ("medium", "600x400x250 mm"),
        ("large", "800x600x300 mm"),
        ("xl", "1200x800x400 mm"),
    ]):
        session.add(_char_val(tid, c_panel_size, v, l, i))

    # --- num_io (numeric, panels) ---
    c_num_io = Characteristic(
        tenant_id=tid, group_id=grp_electrical.id,
        name="I/O Point Count", slug="num-io",
        char_type=CharacteristicType.NUMERIC, is_required=True,
        numeric_min=8, numeric_max=256, numeric_step=8, unit="points",
    )
    session.add(c_num_io)

    # --- protocol (enum, multi-select, panels/HMI) ---
    c_protocol = Characteristic(
        tenant_id=tid, group_id=grp_interface.id,
        name="Communication Protocol", slug="protocol",
        char_type=CharacteristicType.ENUM, is_required=True,
        is_multi_select=True,
    )
    session.add(c_protocol)
    await session.flush()
    for i, (v, l, adj) in enumerate([
        ("modbus-rtu", "Modbus RTU", None),
        ("modbus-tcp", "Modbus TCP/IP", Decimal("25.00")),
        ("profinet", "PROFINET", Decimal("65.00")),
        ("ethercat", "EtherCAT", Decimal("75.00")),
        ("ethernet-ip", "EtherNet/IP", Decimal("60.00")),
    ]):
        session.add(_char_val(tid, c_protocol, v, l, i, adj))

    # --- screen_size (enum, HMI only) ---
    c_screen = Characteristic(
        tenant_id=tid, group_id=grp_interface.id,
        name="Screen Size", slug="screen-size",
        char_type=CharacteristicType.ENUM, is_required=True,
    )
    session.add(c_screen)
    await session.flush()
    for i, (v, l) in enumerate([
        ("7inch", "7\" Widescreen"),
        ("10inch", "10.1\" Widescreen"),
        ("15inch", "15.6\" Widescreen"),
    ]):
        session.add(_char_val(tid, c_screen, v, l, i))

    # --- material (enum, panels) ---
    c_material = Characteristic(
        tenant_id=tid, group_id=grp_mechanical.id,
        name="Enclosure Material", slug="material",
        char_type=CharacteristicType.ENUM, is_required=True,
    )
    session.add(c_material)
    await session.flush()
    for i, (v, l) in enumerate([
        ("mild-steel", "Mild Steel (powder-coated)"),
        ("stainless-304", "Stainless Steel 304"),
        ("stainless-316", "Stainless Steel 316L"),
        ("aluminium", "Die-Cast Aluminium"),
    ]):
        session.add(_char_val(tid, c_material, v, l, i))

    await session.flush()
    print(f"  Created 12 characteristics with values")

    # ════════════════════════════════════════════════════════
    # CHARACTERISTIC ASSIGNMENTS
    # ════════════════════════════════════════════════════════

    assigns = [
        # AC Motor: voltage, power, frame, mounting, ip, brake
        _assign(tid, prod_ac, c_voltage, 0),
        _assign(tid, prod_ac, c_power, 1),
        _assign(tid, prod_ac, c_frame, 2),
        _assign(tid, prod_ac, c_mounting, 3),
        _assign(tid, prod_ac, c_ip, 4),
        _assign(tid, prod_ac, c_brake, 5, required=False, default="false"),

        # Servo Motor: voltage, power, frame, encoder, ip
        _assign(tid, prod_servo, c_voltage, 0),
        _assign(tid, prod_servo, c_power, 1),
        _assign(tid, prod_servo, c_frame, 2),
        _assign(tid, prod_servo, c_encoder, 3),
        _assign(tid, prod_servo, c_ip, 4),

        # Standard Panel: panel_size, voltage, num_io, protocol, material
        _assign(tid, prod_panel, c_panel_size, 0),
        _assign(tid, prod_panel, c_voltage, 1),
        _assign(tid, prod_panel, c_num_io, 2, default="32"),
        _assign(tid, prod_panel, c_protocol, 3, min_sel=1, max_sel=3),
        _assign(tid, prod_panel, c_material, 4),

        # HMI Panel: screen_size, protocol, panel_size, ip
        _assign(tid, prod_hmi, c_screen, 0),
        _assign(tid, prod_hmi, c_protocol, 1, min_sel=1, max_sel=2),
        _assign(tid, prod_hmi, c_panel_size, 2),
        _assign(tid, prod_hmi, c_ip, 3, default="ip55"),
    ]
    session.add_all(assigns)
    await session.flush()
    print(f"  Created {len(assigns)} characteristic assignments")

    # ════════════════════════════════════════════════════════
    # VARIANT TABLE (frame → weight lookup for AC motor)
    # ════════════════════════════════════════════════════════

    vt_weight = VariantTable(
        tenant_id=tid, product_id=prod_ac.id,
        name="Frame-to-Weight Lookup",
        description="Maps IEC frame size to motor weight (kg)",
        columns=[
            {"name": "frame-size", "type": "input"},
            {"name": "weight-kg", "type": "output"},
        ],
        rows=[
            {"frame-size": "71", "weight-kg": "5.2"},
            {"frame-size": "80", "weight-kg": "8.0"},
            {"frame-size": "90", "weight-kg": "12.5"},
            {"frame-size": "100", "weight-kg": "18.0"},
            {"frame-size": "112", "weight-kg": "27.0"},
            {"frame-size": "132", "weight-kg": "45.0"},
            {"frame-size": "160", "weight-kg": "75.0"},
            {"frame-size": "180", "weight-kg": "95.0"},
            {"frame-size": "200", "weight-kg": "135.0"},
        ],
        input_columns=["frame-size"],
        output_columns=["weight-kg"],
    )
    session.add(vt_weight)
    await session.flush()
    print(f"  Created 1 variant table")

    # ════════════════════════════════════════════════════════
    # CONSTRAINT RULES
    # ════════════════════════════════════════════════════════

    # -- AC Motor constraints --
    cg_ac = ConstraintGroup(
        tenant_id=tid, product_id=prod_ac.id,
        name="AC Motor Rules", is_active=True,
    )
    session.add(cg_ac)
    await session.flush()

    ac_rules = [
        # Single-phase only available up to 3 kW
        _rule(tid, prod_ac, cg_ac,
              "Single-phase max 3kW", ConstraintType.EXCLUDES,
              {"if": {"char": "voltage", "op": "eq", "value": "230v-1ph"},
               "then": {"char": "power-rating", "op": "gt", "value": "3.0"}}),

        # 690V requires frame >= 132
        _rule(tid, prod_ac, cg_ac,
              "690V requires large frame", ConstraintType.REQUIRES,
              {"if": {"char": "voltage", "op": "eq", "value": "690v-3ph"},
               "then": {"char": "frame-size", "value": ["132", "160", "180", "200"]}}),

        # IP65/66 excludes foot-only mounting (water ingress risk)
        _rule(tid, prod_ac, cg_ac,
              "High IP excludes foot-only mount", ConstraintType.EXCLUDES,
              {"if": {"char": "ip-rating", "op": "in", "value": ["ip65", "ip66"]},
               "then": {"char": "mounting", "value": "b3-foot"}}),

        # Brake requires frame >= 80
        _rule(tid, prod_ac, cg_ac,
              "Brake needs frame 80+", ConstraintType.REQUIRES,
              {"if": {"char": "brake", "op": "eq", "value": "true"},
               "then": {"char": "frame-size",
                        "value": ["80", "90", "100", "112", "132", "160", "180", "200"]}}),

        # Default IP55
        _rule(tid, prod_ac, cg_ac,
              "Default IP55", ConstraintType.DEFAULT_VALUE,
              {"if": {}, "then": {"char": "ip-rating", "value": "ip55"}},
              priority=-10),

        # Power → frame formula: frame = ceil(power * 5.33 + 60)
        _rule(tid, prod_ac, cg_ac,
              "Auto-select frame from power", ConstraintType.FORMULA,
              {"target": "frame-size",
               "value_map": {
                   "0.75": "71", "1.1": "71", "1.5": "80", "2.2": "90",
                   "3.0": "90", "4.0": "100", "5.5": "112", "7.5": "132",
                   "11.0": "132", "15.0": "160", "18.5": "160",
                   "22.0": "180", "30.0": "200",
               },
               "input": "power-rating"},
              priority=5),

        # Frame-to-weight table lookup
        _rule(tid, prod_ac, cg_ac,
              "Weight from frame table", ConstraintType.TABLE,
              {"table_id": str(vt_weight.id),
               "input_columns": ["frame-size"],
               "output_columns": ["weight-kg"]}),

        # Single-phase excludes B35 combined mount
        _rule(tid, prod_ac, cg_ac,
              "1ph excludes B35 mount", ConstraintType.EXCLUDES,
              {"if": {"char": "voltage", "op": "eq", "value": "230v-1ph"},
               "then": {"char": "mounting", "value": "b35-foot-flange"}}),
    ]
    session.add_all(ac_rules)

    # -- Servo Motor constraints --
    cg_servo = ConstraintGroup(
        tenant_id=tid, product_id=prod_servo.id,
        name="Servo Motor Rules", is_active=True,
    )
    session.add(cg_servo)
    await session.flush()

    servo_rules = [
        # Servo only supports 400V and 230V
        _rule(tid, prod_servo, cg_servo,
              "Servo voltage limited", ConstraintType.EXCLUDES,
              {"if": {},
               "then": {"char": "voltage", "value": ["480v-3ph", "690v-3ph"]}}),

        # Absolute multi-turn encoder requires IP65+
        _rule(tid, prod_servo, cg_servo,
              "Multi-turn needs IP65+", ConstraintType.REQUIRES,
              {"if": {"char": "encoder", "op": "eq", "value": "absolute-multi"},
               "then": {"char": "ip-rating", "value": ["ip65", "ip66"]}}),

        # Power > 15kW requires frame 160+
        _rule(tid, prod_servo, cg_servo,
              "High power needs large frame", ConstraintType.REQUIRES,
              {"if": {"char": "power-rating", "op": "gt", "value": "15"},
               "then": {"char": "frame-size",
                        "value": ["160", "180", "200"]}}),

        # Default encoder
        _rule(tid, prod_servo, cg_servo,
              "Default incremental encoder", ConstraintType.DEFAULT_VALUE,
              {"if": {}, "then": {"char": "encoder", "value": "incremental-1024"}},
              priority=-10),

        # Auto frame from power (servo)
        _rule(tid, prod_servo, cg_servo,
              "Servo frame from power", ConstraintType.FORMULA,
              {"target": "frame-size",
               "value_map": {
                   "0.75": "71", "1.5": "80", "3.0": "90",
                   "5.5": "100", "7.5": "112", "11.0": "132",
                   "15.0": "160", "22.0": "180", "30.0": "200",
               },
               "input": "power-rating"},
              priority=5),

        # IP66 requires absolute encoder (environmental sealing synergy)
        _rule(tid, prod_servo, cg_servo,
              "IP66 requires absolute encoder", ConstraintType.REQUIRES,
              {"if": {"char": "ip-rating", "op": "eq", "value": "ip66"},
               "then": {"char": "encoder",
                        "value": ["absolute-single", "absolute-multi"]}}),
    ]
    session.add_all(servo_rules)

    # -- Standard Panel constraints --
    cg_panel = ConstraintGroup(
        tenant_id=tid, product_id=prod_panel.id,
        name="Panel Rules", is_active=True,
    )
    session.add(cg_panel)
    await session.flush()

    panel_rules = [
        # >128 I/O needs large or xl enclosure
        _rule(tid, prod_panel, cg_panel,
              "High I/O needs large enclosure", ConstraintType.REQUIRES,
              {"if": {"char": "num-io", "op": "gt", "value": "128"},
               "then": {"char": "panel-size", "value": ["large", "xl"]}}),

        # PROFINET requires Modbus TCP as well (gateway)
        _rule(tid, prod_panel, cg_panel,
              "PROFINET needs Modbus TCP", ConstraintType.REQUIRES,
              {"if": {"char": "protocol", "op": "eq", "value": "profinet"},
               "then": {"char": "protocol", "value": "modbus-tcp"}}),

        # 690V only with large/xl panels
        _rule(tid, prod_panel, cg_panel,
              "690V needs large panel", ConstraintType.REQUIRES,
              {"if": {"char": "voltage", "op": "eq", "value": "690v-3ph"},
               "then": {"char": "panel-size", "value": ["large", "xl"]}}),

        # Default material
        _rule(tid, prod_panel, cg_panel,
              "Default mild steel", ConstraintType.DEFAULT_VALUE,
              {"if": {}, "then": {"char": "material", "value": "mild-steel"}},
              priority=-10),

        # Stainless 316L only available in small/medium
        _rule(tid, prod_panel, cg_panel,
              "SS316L only small/medium", ConstraintType.REQUIRES,
              {"if": {"char": "material", "op": "eq", "value": "stainless-316"},
               "then": {"char": "panel-size", "value": ["small", "medium"]}}),
    ]
    session.add_all(panel_rules)

    # -- HMI Touch Panel constraints --
    cg_hmi = ConstraintGroup(
        tenant_id=tid, product_id=prod_hmi.id,
        name="HMI Rules", is_active=True,
    )
    session.add(cg_hmi)
    await session.flush()

    hmi_rules = [
        # 15" screen requires medium+ enclosure
        _rule(tid, prod_hmi, cg_hmi,
              "15\" needs medium+ panel", ConstraintType.REQUIRES,
              {"if": {"char": "screen-size", "op": "eq", "value": "15inch"},
               "then": {"char": "panel-size", "value": ["medium", "large", "xl"]}}),

        # EtherCAT not available on HMI (driver limitation)
        _rule(tid, prod_hmi, cg_hmi,
              "No EtherCAT on HMI", ConstraintType.EXCLUDES,
              {"if": {},
               "then": {"char": "protocol", "value": "ethercat"}}),

        # Default 7" screen
        _rule(tid, prod_hmi, cg_hmi,
              "Default 7\" screen", ConstraintType.DEFAULT_VALUE,
              {"if": {}, "then": {"char": "screen-size", "value": "7inch"}},
              priority=-10),

        # IP66 only with 7" (sealed bezel limitation)
        _rule(tid, prod_hmi, cg_hmi,
              "IP66 only 7\"", ConstraintType.REQUIRES,
              {"if": {"char": "ip-rating", "op": "eq", "value": "ip66"},
               "then": {"char": "screen-size", "value": "7inch"}}),
    ]
    session.add_all(hmi_rules)
    await session.flush()

    total_rules = len(ac_rules) + len(servo_rules) + len(panel_rules) + len(hmi_rules)
    print(f"  Created {total_rules} constraint rules in 4 groups")

    # ════════════════════════════════════════════════════════
    # BOMs (150% Super BOMs)
    # ════════════════════════════════════════════════════════

    # ── AC Motor BOM ────────────────────────────────────────
    bom_ac = BOMHeader(
        tenant_id=tid, product_id=prod_ac.id,
        name="AC Motor Manufacturing BOM", bom_type="manufacturing", is_primary=True,
    )
    session.add(bom_ac)
    await session.flush()

    # Stator assembly (phantom — children roll up)
    ac_stator = _bom_item(tid, bom_ac, "ACM-STATOR-ASY", "Stator Assembly",
                          item_type=BOMItemType.PHANTOM, unit_cost=Decimal("0"), sort=0)
    session.add(ac_stator)
    await session.flush()

    ac_items = [
        # Stator children
        _bom_item(tid, bom_ac, "ACM-LAMINATION", "Stator Lamination Stack",
                  unit_cost=Decimal("22.50"), parent=ac_stator, sort=1),
        _bom_item(tid, bom_ac, "ACM-WINDING-CU", "Copper Winding Set",
                  unit_cost=Decimal("35.00"), parent=ac_stator, sort=2,
                  qty_expr={"type": "formula", "expression": "power * 0.8 + 2",
                            "variables": {"power": "power-rating"}}),

        # Rotor (always included)
        _bom_item(tid, bom_ac, "ACM-ROTOR-ASY", "Rotor Assembly",
                  unit_cost=Decimal("28.00"), sort=3),

        # Frame — conditional on frame size via quantity expression
        _bom_item(tid, bom_ac, "ACM-FRAME", "Motor Frame Casting",
                  unit_cost=Decimal("18.00"), sort=4,
                  qty_expr={"type": "formula", "expression": "1",
                            "variables": {}}),

        # Terminal box — different for single/three-phase
        _bom_item(tid, bom_ac, "ACM-TBOX-1PH", "Terminal Box (single-phase)",
                  unit_cost=Decimal("8.50"), sort=5,
                  condition={"char": "voltage", "op": "eq", "value": "230v-1ph"}),
        _bom_item(tid, bom_ac, "ACM-TBOX-3PH", "Terminal Box (three-phase)",
                  unit_cost=Decimal("12.00"), sort=6,
                  condition={"char": "voltage", "op": "neq", "value": "230v-1ph"}),

        # Bearings (always 2x)
        _bom_item(tid, bom_ac, "ACM-BEARING-DE", "Drive-End Bearing",
                  qty=Decimal("1"), unit_cost=Decimal("6.50"), sort=7),
        _bom_item(tid, bom_ac, "ACM-BEARING-NDE", "Non-Drive-End Bearing",
                  qty=Decimal("1"), unit_cost=Decimal("5.80"), sort=8),

        # Brake module (only if brake == true)
        _bom_item(tid, bom_ac, "ACM-BRAKE-MOD", "Electromagnetic Brake Module",
                  unit_cost=Decimal("65.00"), sort=9,
                  condition={"char": "brake", "op": "eq", "value": "true"}),

        # Sealing kit — only for IP65/66
        _bom_item(tid, bom_ac, "ACM-SEAL-KIT", "IP65/66 Sealing Kit",
                  unit_cost=Decimal("14.00"), sort=10,
                  condition={"char": "ip-rating", "op": "in",
                             "value": ["ip65", "ip66"]}),

        # Mounting adapter (flange variants)
        _bom_item(tid, bom_ac, "ACM-FLANGE-ADAPT", "Flange Mounting Adapter",
                  unit_cost=Decimal("22.00"), sort=11,
                  condition={"char": "mounting", "op": "in",
                             "value": ["b5-flange", "b14-face", "b35-foot-flange"]}),
    ]
    session.add_all(ac_items)

    # ── Servo Motor BOM ─────────────────────────────────────
    bom_servo = BOMHeader(
        tenant_id=tid, product_id=prod_servo.id,
        name="Servo Motor Manufacturing BOM", bom_type="manufacturing", is_primary=True,
    )
    session.add(bom_servo)
    await session.flush()

    servo_items = [
        _bom_item(tid, bom_servo, "SRV-STATOR", "Servo Stator Assembly",
                  unit_cost=Decimal("55.00"), sort=0),
        _bom_item(tid, bom_servo, "SRV-ROTOR-PM", "Permanent Magnet Rotor",
                  unit_cost=Decimal("72.00"), sort=1),
        _bom_item(tid, bom_servo, "SRV-FRAME", "Servo Frame Housing",
                  unit_cost=Decimal("32.00"), sort=2),
        _bom_item(tid, bom_servo, "SRV-BEARING-DE", "Precision Drive-End Bearing",
                  unit_cost=Decimal("12.00"), sort=3),
        _bom_item(tid, bom_servo, "SRV-BEARING-NDE", "Precision NDE Bearing",
                  unit_cost=Decimal("10.50"), sort=4),

        # Encoder variants
        _bom_item(tid, bom_servo, "SRV-ENC-INC1K", "Incremental Encoder 1024 PPR",
                  unit_cost=Decimal("28.00"), sort=5,
                  condition={"char": "encoder", "op": "eq", "value": "incremental-1024"}),
        _bom_item(tid, bom_servo, "SRV-ENC-INC4K", "Incremental Encoder 4096 PPR",
                  unit_cost=Decimal("52.00"), sort=6,
                  condition={"char": "encoder", "op": "eq", "value": "incremental-4096"}),
        _bom_item(tid, bom_servo, "SRV-ENC-ABS-S", "Absolute Single-Turn Encoder",
                  unit_cost=Decimal("95.00"), sort=7,
                  condition={"char": "encoder", "op": "eq", "value": "absolute-single"}),
        _bom_item(tid, bom_servo, "SRV-ENC-ABS-M", "Absolute Multi-Turn Encoder",
                  unit_cost=Decimal("145.00"), sort=8,
                  condition={"char": "encoder", "op": "eq", "value": "absolute-multi"}),

        # Resolver feedback cable (always included)
        _bom_item(tid, bom_servo, "SRV-CABLE-FB", "Feedback Cable Assembly",
                  unit_cost=Decimal("18.00"), sort=9),
    ]
    session.add_all(servo_items)

    # ── Standard Panel BOM ──────────────────────────────────
    bom_panel = BOMHeader(
        tenant_id=tid, product_id=prod_panel.id,
        name="Standard Panel Assembly BOM", bom_type="manufacturing", is_primary=True,
    )
    session.add(bom_panel)
    await session.flush()

    # Enclosure phantom (children get promoted)
    panel_encl = _bom_item(tid, bom_panel, "SCP-ENCL-ASY", "Enclosure Assembly",
                           item_type=BOMItemType.PHANTOM, unit_cost=Decimal("0"), sort=0)
    session.add(panel_encl)
    await session.flush()

    panel_items = [
        # Enclosure body — mild steel variant
        _bom_item(tid, bom_panel, "SCP-ENCL-MS", "Mild Steel Enclosure",
                  unit_cost=Decimal("45.00"), parent=panel_encl, sort=1,
                  condition={"char": "material", "op": "eq", "value": "mild-steel"}),
        _bom_item(tid, bom_panel, "SCP-ENCL-SS304", "Stainless 304 Enclosure",
                  unit_cost=Decimal("95.00"), parent=panel_encl, sort=2,
                  condition={"char": "material", "op": "eq", "value": "stainless-304"}),
        _bom_item(tid, bom_panel, "SCP-ENCL-SS316", "Stainless 316L Enclosure",
                  unit_cost=Decimal("135.00"), parent=panel_encl, sort=3,
                  condition={"char": "material", "op": "eq", "value": "stainless-316"}),
        _bom_item(tid, bom_panel, "SCP-ENCL-ALU", "Aluminium Enclosure",
                  unit_cost=Decimal("72.00"), parent=panel_encl, sort=4,
                  condition={"char": "material", "op": "eq", "value": "aluminium"}),

        # DIN rail (always, quantity depends on I/O count)
        _bom_item(tid, bom_panel, "SCP-DINRAIL", "DIN Rail 35mm",
                  unit_cost=Decimal("3.50"), sort=5,
                  qty_expr={"type": "formula", "expression": "io / 16 + 1",
                            "variables": {"io": "num-io"}}),

        # PLC module (always)
        _bom_item(tid, bom_panel, "SCP-PLC-CPU", "PLC CPU Module",
                  unit_cost=Decimal("180.00"), sort=6),

        # I/O modules — quantity from I/O point count
        _bom_item(tid, bom_panel, "SCP-IO-MOD", "I/O Expansion Module (16-pt)",
                  unit_cost=Decimal("42.00"), sort=7,
                  qty_expr={"type": "formula", "expression": "io / 16",
                            "variables": {"io": "num-io"}}),

        # Protocol interface cards
        _bom_item(tid, bom_panel, "SCP-IF-PNET", "PROFINET Interface Card",
                  unit_cost=Decimal("85.00"), sort=8,
                  condition={"char": "protocol", "op": "eq", "value": "profinet"}),
        _bom_item(tid, bom_panel, "SCP-IF-ECAT", "EtherCAT Interface Card",
                  unit_cost=Decimal("92.00"), sort=9,
                  condition={"char": "protocol", "op": "eq", "value": "ethercat"}),
        _bom_item(tid, bom_panel, "SCP-IF-EIP", "EtherNet/IP Interface Card",
                  unit_cost=Decimal("78.00"), sort=10,
                  condition={"char": "protocol", "op": "eq", "value": "ethernet-ip"}),

        # Power supply (always)
        _bom_item(tid, bom_panel, "SCP-PSU-24V", "24V DC Power Supply",
                  unit_cost=Decimal("55.00"), sort=11),
    ]
    session.add_all(panel_items)

    # ── HMI Touch Panel BOM ─────────────────────────────────
    bom_hmi = BOMHeader(
        tenant_id=tid, product_id=prod_hmi.id,
        name="HMI Panel Assembly BOM", bom_type="manufacturing", is_primary=True,
    )
    session.add(bom_hmi)
    await session.flush()

    hmi_items = [
        # Screen variants
        _bom_item(tid, bom_hmi, "HMI-LCD-7", "7\" TFT LCD Module",
                  unit_cost=Decimal("62.00"), sort=0,
                  condition={"char": "screen-size", "op": "eq", "value": "7inch"}),
        _bom_item(tid, bom_hmi, "HMI-LCD-10", "10.1\" TFT LCD Module",
                  unit_cost=Decimal("95.00"), sort=1,
                  condition={"char": "screen-size", "op": "eq", "value": "10inch"}),
        _bom_item(tid, bom_hmi, "HMI-LCD-15", "15.6\" TFT LCD Module",
                  unit_cost=Decimal("142.00"), sort=2,
                  condition={"char": "screen-size", "op": "eq", "value": "15inch"}),

        # Touch digitizer (always)
        _bom_item(tid, bom_hmi, "HMI-TOUCH-CAP", "Capacitive Touch Digitizer",
                  unit_cost=Decimal("35.00"), sort=3),

        # SBC controller board (always)
        _bom_item(tid, bom_hmi, "HMI-SBC", "HMI Controller Board (ARM)",
                  unit_cost=Decimal("48.00"), sort=4),

        # Comm modules
        _bom_item(tid, bom_hmi, "HMI-COM-MBTCP", "Modbus TCP Module",
                  unit_cost=Decimal("18.00"), sort=5,
                  condition={"char": "protocol", "op": "eq", "value": "modbus-tcp"}),
        _bom_item(tid, bom_hmi, "HMI-COM-PNET", "PROFINET Comm Module",
                  unit_cost=Decimal("55.00"), sort=6,
                  condition={"char": "protocol", "op": "eq", "value": "profinet"}),
        _bom_item(tid, bom_hmi, "HMI-COM-EIP", "EtherNet/IP Comm Module",
                  unit_cost=Decimal("48.00"), sort=7,
                  condition={"char": "protocol", "op": "eq", "value": "ethernet-ip"}),

        # Bezel / front panel (always)
        _bom_item(tid, bom_hmi, "HMI-BEZEL", "Front Bezel Assembly",
                  unit_cost=Decimal("15.00"), sort=8),
    ]
    session.add_all(hmi_items)
    await session.flush()

    bom_count = len(ac_items) + 1 + len(servo_items) + len(panel_items) + 1 + len(hmi_items)
    print(f"  Created 4 BOMs with {bom_count} total items (incl. 2 phantoms)")

    # ════════════════════════════════════════════════════════
    # PRICING RULES
    # ════════════════════════════════════════════════════════

    pricing_rules = [
        # AC Motor pricing
        _pricing(tid, prod_ac, "AC Motor Base Price",
                 PricingRuleType.BASE_PRICE, {"amount": "250"}, priority=0),
        _pricing(tid, prod_ac, "AC Motor Power Surcharge",
                 PricingRuleType.CONDITIONAL,
                 {"condition": {"char": "power-rating", "op": "gt", "value": "7.5"},
                  "adjustment_type": "percentage", "amount": "15"},
                 priority=10),
        _pricing(tid, prod_ac, "AC Motor Brake Surcharge",
                 PricingRuleType.OPTION_SURCHARGE,
                 {"condition": {"char": "brake", "op": "eq", "value": "true"},
                  "amount": "120"},
                 priority=10),
        _pricing(tid, prod_ac, "AC Motor Volume Discount",
                 PricingRuleType.TIERED,
                 {"tiers": [
                     {"min": 1, "max": 9, "price": "0"},
                     {"min": 10, "max": 49, "price": "-12.50"},
                     {"min": 50, "max": None, "price": "-25.00"},
                 ],
                  "tier_model": "all_units",
                  "quantity_source": "bom_total"},
                 priority=20),

        # Servo Motor pricing
        _pricing(tid, prod_servo, "Servo Base Price",
                 PricingRuleType.BASE_PRICE, {"amount": "450"}, priority=0),
        _pricing(tid, prod_servo, "Servo Encoder Premium",
                 PricingRuleType.CONDITIONAL,
                 {"condition": {"char": "encoder", "op": "in",
                                "value": ["absolute-single", "absolute-multi"]},
                  "adjustment_type": "fixed", "amount": "75"},
                 priority=10),
        _pricing(tid, prod_servo, "Servo Margin Floor",
                 PricingRuleType.MARGIN, {"min_margin_pct": "25"}, priority=99),

        # Standard Panel pricing
        _pricing(tid, prod_panel, "Panel Base Price",
                 PricingRuleType.BASE_PRICE, {"amount": "380"}, priority=0),
        _pricing(tid, prod_panel, "Panel I/O Tiered Pricing",
                 PricingRuleType.TIERED,
                 {"tiers": [
                     {"min": 8, "max": 32, "price": "5.00"},
                     {"min": 33, "max": 128, "price": "4.50"},
                     {"min": 129, "max": 256, "price": "4.00"},
                 ],
                  "tier_model": "marginal",
                  "quantity_source": "characteristic",
                  "quantity_key": "num-io"},
                 priority=10),
        _pricing(tid, prod_panel, "Panel SS316 Surcharge",
                 PricingRuleType.OPTION_SURCHARGE,
                 {"condition": {"char": "material", "op": "eq", "value": "stainless-316"},
                  "amount": "180"},
                 priority=10),

        # HMI pricing
        _pricing(tid, prod_hmi, "HMI Base Price",
                 PricingRuleType.BASE_PRICE, {"amount": "290"}, priority=0),
        _pricing(tid, prod_hmi, "HMI Large Screen Surcharge",
                 PricingRuleType.CONDITIONAL,
                 {"condition": {"char": "screen-size", "op": "eq", "value": "15inch"},
                  "adjustment_type": "fixed", "amount": "85"},
                 priority=10),
    ]
    session.add_all(pricing_rules)
    await session.flush()
    print(f"  Created {len(pricing_rules)} pricing rules")

    # ════════════════════════════════════════════════════════
    # COMMIT
    # ════════════════════════════════════════════════════════

    await session.commit()
    print()
    print("=" * 60)
    print("  Configurator test environment seeded successfully!")
    print("=" * 60)
    print()
    print("  Families:        2 (Industrial Motors, Control Panels)")
    print(f"  Products:        4")
    print(f"  Characteristics: 12 (shared across products)")
    print(f"  Assignments:     {len(assigns)}")
    print(f"  Constraint rules:{total_rules}")
    print(f"  Variant tables:  1")
    print(f"  BOM items:       {bom_count}")
    print(f"  Pricing rules:   {len(pricing_rules)}")
    print()
    print("  Products:")
    print(f"    1. {prod_ac.name:<30} [{prod_ac.slug}]")
    print(f"    2. {prod_servo.name:<30} [{prod_servo.slug}]")
    print(f"    3. {prod_panel.name:<30} [{prod_panel.slug}]")
    print(f"    4. {prod_hmi.name:<30} [{prod_hmi.slug}]")
    print()


async def main() -> None:
    print("Seeding configurator test environment...")
    async with async_session_factory() as session:
        await seed(session)
    await dispose_engines()


if __name__ == "__main__":
    asyncio.run(main())

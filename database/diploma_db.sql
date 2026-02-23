-- ============================================================
-- Warehouse Robot DB schema (PostgreSQL) - FINAL
-- Recreate-from-scratch version
-- ============================================================

DROP TABLE IF EXISTS tasks CASCADE;
DROP TABLE IF EXISTS inbound_lines CASCADE;
DROP TABLE IF EXISTS inbounds CASCADE;
DROP TABLE IF EXISTS products CASCADE;

DROP TABLE IF EXISTS slot_state CASCADE;
DROP TABLE IF EXISTS shelf_slots CASCADE;
DROP TABLE IF EXISTS shelves CASCADE;

-- -------------------------
-- SHELVES
-- -------------------------
CREATE TABLE shelves (
    shelf_id    SERIAL PRIMARY KEY,
    shelf_code  VARCHAR(10) NOT NULL UNIQUE,
    description TEXT,
    role        VARCHAR(16) NOT NULL DEFAULT 'PICK',

    map_x   DOUBLE PRECISION,
    map_y   DOUBLE PRECISION,
    map_yaw DOUBLE PRECISION,

    CONSTRAINT chk_shelves_role
        CHECK (role IN ('PICK', 'STORAGE', 'DELIVERY'))
);

-- -------------------------
-- SHELF SLOTS
-- -------------------------
CREATE TABLE shelf_slots (
    slot_id     SERIAL PRIMARY KEY,
    shelf_code  VARCHAR(10) NOT NULL,
    side        VARCHAR(5)  NOT NULL,
    level       VARCHAR(10) NOT NULL DEFAULT 'UPPER',

    apriltag_id INTEGER,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT fk_shelf_slots_shelf
        FOREIGN KEY (shelf_code)
        REFERENCES shelves (shelf_code)
        ON DELETE CASCADE,

    -- IMPORTANT: include level, otherwise UPPER/LOWER cannot coexist
    CONSTRAINT uq_shelf_side_level
        UNIQUE (shelf_code, side, level),

    CONSTRAINT chk_shelf_slots_side
        CHECK (side IN ('LEFT', 'RIGHT')),

    CONSTRAINT chk_shelf_slots_level
        CHECK (level IN ('UPPER', 'LOWER'))
);

CREATE INDEX idx_shelf_slots_shelf_code ON shelf_slots(shelf_code);
CREATE INDEX idx_shelf_slots_apriltag   ON shelf_slots(apriltag_id);
CREATE INDEX idx_shelf_slots_enabled    ON shelf_slots(enabled);

-- -------------------------
-- PRODUCTS
-- -------------------------
CREATE TABLE products (
    product_id    SERIAL PRIMARY KEY,
    sku           VARCHAR(64)  NOT NULL,
    manufacturer  VARCHAR(128) NOT NULL,
    name          VARCHAR(128) NOT NULL,

    CONSTRAINT uq_product UNIQUE (sku, manufacturer)
);

CREATE INDEX idx_products_sku  ON products(sku);
CREATE INDEX idx_products_manu ON products(manufacturer);

-- -------------------------
-- SLOT STATE (1:1 with shelf_slots)
-- Stores "what is in the slot" using product_id + stored_at for FIFO
-- cube_qr can be kept for validation (what robot actually saw)
-- -------------------------
CREATE TABLE slot_state (
    slot_id           INTEGER PRIMARY KEY,
    reserved_task_id  INTEGER,

    occupied   BOOLEAN NOT NULL DEFAULT FALSE,
    reserved   BOOLEAN NOT NULL DEFAULT FALSE,

    product_id INTEGER,
    stored_at  TIMESTAMP,

    cube_qr    VARCHAR(255),

    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    robot_id   VARCHAR(50),

    CONSTRAINT fk_slot_state_slot
        FOREIGN KEY (slot_id)
        REFERENCES shelf_slots (slot_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_slot_state_product
        FOREIGN KEY (product_id)
        REFERENCES products (product_id)
        ON DELETE RESTRICT,

    -- reserved flag must match reserved_task_id
    CONSTRAINT chk_slot_state_reserved_task
        CHECK (
            (reserved = false AND reserved_task_id IS NULL)
         OR (reserved = true  AND reserved_task_id IS NOT NULL)
        ),

    -- inventory consistency: empty slot -> no product/stored_at
    CONSTRAINT chk_slot_state_inventory
        CHECK (
            (occupied = false AND product_id IS NULL AND stored_at IS NULL)
         OR (occupied = true  AND product_id IS NOT NULL AND stored_at IS NOT NULL)
        )
);

CREATE INDEX idx_slot_state_occupied ON slot_state(occupied);
CREATE INDEX idx_slot_state_reserved ON slot_state(reserved);
CREATE INDEX idx_slot_state_updated  ON slot_state(updated_at);
CREATE INDEX idx_slot_state_product  ON slot_state(product_id);

-- FIFO index: fastest "pick oldest available unit"
CREATE INDEX idx_slot_state_fifo_pick
ON slot_state (product_id, stored_at)
WHERE occupied = true AND reserved = false;

-- -------------------------
-- INBOUNDS (document header)
-- -------------------------
CREATE TABLE inbounds (
    inbound_id SERIAL PRIMARY KEY,

    source       VARCHAR(128),
    external_ref VARCHAR(64),
    file_name    VARCHAR(255),
    file_hash    VARCHAR(64),

    status       VARCHAR(16) NOT NULL DEFAULT 'NEW',
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);

-- -------------------------
-- INBOUND LINES (document lines)
-- -------------------------
CREATE TABLE inbound_lines (
    inbound_line_id SERIAL PRIMARY KEY,

    inbound_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity   INTEGER NOT NULL CHECK (quantity > 0),

    status     VARCHAR(16) NOT NULL DEFAULT 'NEW',
    created_at TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_inbound_lines_inbound
        FOREIGN KEY (inbound_id)
        REFERENCES inbounds (inbound_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_inbound_lines_product
        FOREIGN KEY (product_id)
        REFERENCES products (product_id)
        ON DELETE RESTRICT
);

CREATE INDEX idx_inbound_lines_inbound ON inbound_lines(inbound_id);
CREATE INDEX idx_inbound_lines_product ON inbound_lines(product_id);
CREATE INDEX idx_inbound_lines_status  ON inbound_lines(status);

-- -------------------------
-- TASKS
-- PUTAWAY: inbound_line_id MUST be NOT NULL
-- DELIVERY: inbound_line_id MUST be NULL (created from UI/operator request)
-- -------------------------
CREATE TABLE tasks (
    task_id SERIAL PRIMARY KEY,

    source_slot_id INTEGER,
    target_slot_id INTEGER,

    inbound_line_id INTEGER,      -- NOW nullable (important)
    product_id      INTEGER NOT NULL,

    status   VARCHAR(16) NOT NULL DEFAULT 'NEW',
    type     VARCHAR(16) NOT NULL DEFAULT 'PUTAWAY',
    robot_id VARCHAR(32),

    -- what robot reported (optional; can be used for validation)
    observed_sku          VARCHAR(64),
    observed_manufacturer VARCHAR(64),

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,

    CONSTRAINT fk_task_product
        FOREIGN KEY (product_id)
        REFERENCES products (product_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_task_inbound
        FOREIGN KEY (inbound_line_id)
        REFERENCES inbound_lines (inbound_line_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_task_source_slot
        FOREIGN KEY (source_slot_id)
        REFERENCES shelf_slots (slot_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_task_target_slot
        FOREIGN KEY (target_slot_id)
        REFERENCES shelf_slots (slot_id)
        ON DELETE RESTRICT,

    CONSTRAINT chk_task_type
        CHECK (type IN ('PUTAWAY', 'DELIVERY')),

    -- key rule: inbound is required only for PUTAWAY
    CONSTRAINT chk_task_putaway_requires_inbound
        CHECK (
            (type = 'PUTAWAY'  AND inbound_line_id IS NOT NULL)
         OR (type = 'DELIVERY' AND inbound_line_id IS NULL)
        )
);

CREATE INDEX idx_tasks_status       ON tasks(status);
CREATE INDEX idx_tasks_type         ON tasks(type);
CREATE INDEX idx_tasks_product      ON tasks(product_id);
CREATE INDEX idx_tasks_inbound_line ON tasks(inbound_line_id);

-- ============================================================
-- SEED EXAMPLE
-- ============================================================
INSERT INTO shelves (shelf_code, description, role)
VALUES
  ('A', 'Pick point', 'PICK'),
  ('B', 'Shelf B', 'STORAGE'),
  ('C', 'Delivery point', 'DELIVERY');

-- Example shelf coordinates
UPDATE shelves SET map_x = 0.0, map_y = 0.7,  map_yaw =  3.14 WHERE shelf_code = 'A';
UPDATE shelves SET map_x = 1.5, map_y = -1.5, map_yaw =  0.00 WHERE shelf_code = 'B';
UPDATE shelves SET map_x = 1.5, map_y = -1.5, map_yaw =  3.14 WHERE shelf_code = 'C';

-- Create slots: A/B/C, LEFT/RIGHT, UPPER/LOWER where needed
INSERT INTO shelf_slots (shelf_code, side, level, apriltag_id, enabled)
VALUES
  ('A', 'RIGHT', 'UPPER', 0, true),
  ('A', 'LEFT',  'UPPER', 0, true),

  ('B', 'RIGHT', 'UPPER', 1, true),
  ('B', 'LEFT',  'UPPER', 1, true),
  ('B', 'RIGHT', 'LOWER', 1, true),
  ('B', 'LEFT',  'LOWER', 1, true),

  ('C', 'RIGHT', 'UPPER', 2, true),
  ('C', 'LEFT',  'UPPER', 2, true);

-- Initialize slot_state rows (1:1 per slot)
INSERT INTO slot_state (slot_id, occupied, reserved, reserved_task_id, product_id, stored_at, cube_qr, updated_at, robot_id)
SELECT slot_id, false, false, NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, NULL
FROM shelf_slots;

-- Quick checks
SELECT slot_id, shelf_code, side, level, enabled
FROM shelf_slots
ORDER BY shelf_code, side, level;

SELECT ss.shelf_code, ss.side, ss.level,
       st.occupied, st.reserved, st.product_id, st.stored_at,
       st.cube_qr, st.updated_at, st.robot_id
FROM slot_state st
JOIN shelf_slots ss ON ss.slot_id = st.slot_id
ORDER BY ss.shelf_code, ss.side, ss.level;
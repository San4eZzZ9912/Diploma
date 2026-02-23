-- ============================================================
-- Warehouse Robot DB schema (PostgreSQL) - FINAL (Inbound + Outbound)
-- Recreate-from-scratch version
-- ============================================================

DROP TABLE IF EXISTS tasks CASCADE;

DROP TABLE IF EXISTS outbound_lines CASCADE;
DROP TABLE IF EXISTS outbounds CASCADE;

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
-- "Что лежит в слоте" = product_id + stored_at (FIFO)
-- cube_qr можно оставить для валидации (что робот реально увидел)
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

    CONSTRAINT chk_slot_state_reserved_task
        CHECK (
            (reserved = false AND reserved_task_id IS NULL)
         OR (reserved = true  AND reserved_task_id IS NOT NULL)
        ),

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

-- FIFO index: "выбрать самый старый доступный слот"
CREATE INDEX idx_slot_state_fifo_pick
ON slot_state (product_id, stored_at)
WHERE occupied = true AND reserved = false;

-- -------------------------
-- INBOUNDS (приёмка: шапка)
-- -------------------------
CREATE TABLE inbounds (
    inbound_id SERIAL PRIMARY KEY,

    source       VARCHAR(128),
    external_ref VARCHAR(64),
    file_name    VARCHAR(255),

    status       VARCHAR(16) NOT NULL DEFAULT 'NEW',
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
);

-- -------------------------
-- INBOUND LINES (приёмка: строки)
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
-- OUTBOUNDS (отбор/отгрузка: шапка)
-- -------------------------
CREATE TABLE outbounds (
    outbound_id SERIAL PRIMARY KEY,

    external_ref VARCHAR(64),    -- внешний номер заявки (опционально)

    status       VARCHAR(16) NOT NULL DEFAULT 'NEW',
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
);

CREATE INDEX idx_outbounds_status ON outbounds(status);

-- -------------------------
-- OUTBOUND LINES (отбор/отгрузка: строки)
-- -------------------------
CREATE TABLE outbound_lines (
    outbound_line_id SERIAL PRIMARY KEY,

    outbound_id INTEGER NOT NULL,
    product_id  INTEGER NOT NULL,
    quantity    INTEGER NOT NULL CHECK (quantity > 0),

    status      VARCHAR(16) NOT NULL DEFAULT 'NEW',
    created_at  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_outbound_lines_outbound
        FOREIGN KEY (outbound_id)
        REFERENCES outbounds (outbound_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_outbound_lines_product
        FOREIGN KEY (product_id)
        REFERENCES products (product_id)
        ON DELETE RESTRICT
);

CREATE INDEX idx_outbound_lines_outbound ON outbound_lines(outbound_id);
CREATE INDEX idx_outbound_lines_product  ON outbound_lines(product_id);
CREATE INDEX idx_outbound_lines_status   ON outbound_lines(status);

-- -------------------------
-- TASKS
-- Задача относится ЛИБО к inbound_line (PUTAWAY),
-- ЛИБО к outbound_line (DELIVERY)
-- -------------------------
CREATE TABLE tasks (
    task_id SERIAL PRIMARY KEY,

    source_slot_id INTEGER,
    target_slot_id INTEGER,

    inbound_line_id  INTEGER,
    outbound_line_id INTEGER,

    product_id INTEGER NOT NULL,   -- удобно для диспетчера/робота (денормализация)

    status   VARCHAR(16) NOT NULL DEFAULT 'NEW',
    type     VARCHAR(16) NOT NULL DEFAULT 'PUTAWAY',
    robot_id VARCHAR(32),

    observed_sku          VARCHAR(64),
    observed_manufacturer VARCHAR(64),

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,

    CONSTRAINT fk_task_product
        FOREIGN KEY (product_id)
        REFERENCES products (product_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_task_inbound_line
        FOREIGN KEY (inbound_line_id)
        REFERENCES inbound_lines (inbound_line_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_task_outbound_line
        FOREIGN KEY (outbound_line_id)
        REFERENCES outbound_lines (outbound_line_id)
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

    -- строго: одна из ссылок должна быть задана, и она зависит от типа
    CONSTRAINT chk_task_parent_by_type
        CHECK (
            (type = 'PUTAWAY'  AND inbound_line_id  IS NOT NULL AND outbound_line_id IS NULL)
         OR (type = 'DELIVERY' AND inbound_line_id  IS NULL     AND outbound_line_id IS NOT NULL)
        )
);

CREATE INDEX idx_tasks_status        ON tasks(status);
CREATE INDEX idx_tasks_type          ON tasks(type);
CREATE INDEX idx_tasks_product       ON tasks(product_id);
CREATE INDEX idx_tasks_inbound_line  ON tasks(inbound_line_id);
CREATE INDEX idx_tasks_outbound_line ON tasks(outbound_line_id);

-- теперь можно связать slot_state.reserved_task_id -> tasks.task_id (т.к. tasks уже существует)
ALTER TABLE slot_state
ADD CONSTRAINT fk_slot_state_reserved_task
FOREIGN KEY (reserved_task_id)
REFERENCES tasks(task_id)
ON DELETE SET NULL;

-- ============================================================
-- SEED EXAMPLE
-- ============================================================

INSERT INTO shelves (shelf_code, description, role)
VALUES
  ('A', 'Pick point',     'PICK'),
  ('B', 'Shelf B',        'STORAGE'),
  ('C', 'Delivery point', 'DELIVERY');

UPDATE shelves SET map_x = 0.0, map_y = 0.7,  map_yaw =  3.14 WHERE shelf_code = 'A';
UPDATE shelves SET map_x = 1.5, map_y = -1.5, map_yaw =  0.00 WHERE shelf_code = 'B';
UPDATE shelves SET map_x = 1.5, map_y = -1.5, map_yaw =  3.14 WHERE shelf_code = 'C';

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

INSERT INTO slot_state (
    slot_id, reserved_task_id, occupied, reserved, product_id, stored_at, cube_qr, updated_at, robot_id
)
SELECT slot_id, NULL, false, false, NULL, NULL, NULL, CURRENT_TIMESTAMP, NULL
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
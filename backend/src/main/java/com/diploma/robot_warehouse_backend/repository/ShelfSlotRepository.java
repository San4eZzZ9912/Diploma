package com.diploma.robot_warehouse_backend.repository;

import com.diploma.robot_warehouse_backend.entity.ShelfSlot;
import com.diploma.robot_warehouse_backend.enums.Level;
import com.diploma.robot_warehouse_backend.enums.Side;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.Optional;

@Repository
public interface ShelfSlotRepository extends JpaRepository<ShelfSlot, Integer> {
    Optional<ShelfSlot> findByShelf_ShelfCodeAndSideAndLevel(String shelfCode, Side side, Level level);
}

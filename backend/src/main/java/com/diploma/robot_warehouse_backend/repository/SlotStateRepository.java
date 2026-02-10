package com.diploma.robot_warehouse_backend.repository;

import com.diploma.robot_warehouse_backend.entity.SlotState;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;
import java.util.Optional;

@Repository
public interface SlotStateRepository extends JpaRepository<SlotState, Integer> {
    Optional<SlotState> findById(Integer slotId);
    Optional<SlotState> findByReservedTaskId(Integer taskId);

    @Query(value = """
        select ss.*
        from slot_state ss
        join shelf_slots sl on sl.slot_id = ss.slot_id
        join shelves sh on sh.shelf_code = sl.shelf_code
        where ss.occupied = false
          and ss.reserved = false
          and sl.enabled = true
          and sh.role = 'STORAGE'
        order by sh.shelf_code asc, sl.level asc, sl.side asc
        for update skip locked
        limit 1
    """, nativeQuery = true)
    Optional<SlotState> findFirstFreeForUpdate();
}

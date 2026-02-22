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

    @Query(value = """
        select st.*
        from slot_state st
        join shelf_slots ss on ss.slot_id = st.slot_id
        join shelves sh on sh.shelf_code = ss.shelf_code
        where st.occupied = true
          and st.reserved = false
          and st.cube_qr = :cubeQr
          and ss.enabled = true
          and sh.role = 'STORAGE'
        order by st.updated_at asc
        for update skip locked
        limit 1
    """, nativeQuery = true)
    Optional<SlotState> findFirstOccupiedStorageByCubeQrForUpdate(String cubeQr);

    @Query(value = """
        select st.*
        from slot_state st
        join shelf_slots sl on sl.slot_id = st.slot_id
        join shelves sh on sh.shelf_code = sl.shelf_code
        where st.occupied = false
          and st.reserved = false
          and sl.enabled = true
          and sh.role = 'DELIVERY'
          and sl.level = 'UPPER'
        order by sl.side asc
        for update skip locked
        limit 1
    """, nativeQuery = true)
    Optional<SlotState> findFirstFreeDeliveryUpperForUpdate();
}

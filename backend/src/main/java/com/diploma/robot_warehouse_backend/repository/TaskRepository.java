package com.diploma.robot_warehouse_backend.repository;

import com.diploma.robot_warehouse_backend.entity.Task;
import com.diploma.robot_warehouse_backend.enums.Status;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface TaskRepository extends JpaRepository<Task, Integer> {

    @Query(value = """
        select *
        from tasks
        where status = 'NEW'
        order by created_at ASC
        for update skip locked
        limit 1
    """, nativeQuery = true)
    Optional<Task> findNextNewForUpdate();

    @Query(value = """
        select *
        from tasks
        where status = 'NEW' and type = 'DELIVERY'
        order by created_at asc
        for update skip locked
        limit 1
    """, nativeQuery = true)
    Optional<Task> findNextNewDeliveryForUpdate();

    @Query(value = """
        select *
        from tasks
        where status = 'NEW' and type = 'PUTAWAY'
        order by created_at asc
        for update skip locked
        limit 1
    """, nativeQuery = true)
    Optional<Task> findNextNewPutawayForUpdate();


    Optional<Task> findFirstByRobotIdAndStatus(String robotId, Status status);

    @EntityGraph(attributePaths = {
            "product",
            "targetSlot", "targetSlot.shelf",
            "sourceSlot", "sourceSlot.shelf"
    })
    List<Task> findTop50ByStatusOrderByCreatedAtDesc(Status status);

    @EntityGraph(attributePaths = {
            "product",
            "targetSlot", "targetSlot.shelf",
            "sourceSlot", "sourceSlot.shelf"
    })
    List<Task> findTop50ByStatusOrderByUpdatedAtDesc(Status status);

    @EntityGraph(attributePaths = {
            "product",
            "targetSlot", "targetSlot.shelf",
            "sourceSlot", "sourceSlot.shelf"
    })
    List<Task> findTop50ByStatusInOrderByUpdatedAtDesc(List<Status> statuses);

    List<Task> findByOutboundLine_Id(Integer outboundLineId);
    List<Task> findByInboundLine_Id(Integer inboundLineId);

    @Query("""
       select t from Task t
       join fetch t.product
       join fetch t.outboundLine
       where t.outboundLine.outbound.id = :outboundId
       order by t.id
       """)
    List<Task> findByOutboundIdWithProduct(@Param("outboundId") Integer outboundId);

    List<Task> findByOutboundLine_Outbound_IdAndStatus(Integer outboundId, Status status);

    boolean existsByOutboundLine_Outbound_IdAndStatusIn(Integer outboundId, List<Status> statuses);
}

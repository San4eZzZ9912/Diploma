package com.diploma.robot_warehouse_backend.repository;

import com.diploma.robot_warehouse_backend.entity.OutboundLine;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface OutboundLineRepository extends JpaRepository<OutboundLine, Integer> {
    List<OutboundLine> findByOutbound_Id(Integer outboundId);

    @Query("""
       select l from OutboundLine l
       join fetch l.product
       where l.outbound.id = :outboundId
       order by l.id
       """)
    List<OutboundLine> findByOutboundIdWithProduct(@Param("outboundId") Integer outboundId);
}

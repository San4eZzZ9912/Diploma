package com.diploma.robot_warehouse_backend.repository;

import com.diploma.robot_warehouse_backend.entity.OutboundLine;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface OutboundLineRepository extends JpaRepository<OutboundLine, Integer> {
    List<OutboundLine> findByOutbound_Id(Integer outboundId);
}

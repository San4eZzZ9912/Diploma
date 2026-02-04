package com.diploma.robot_warehouse_backend.repository;

import com.diploma.robot_warehouse_backend.entity.InboundLine;
import org.springframework.data.jpa.repository.JpaRepository;

public interface InboundLineRepository extends JpaRepository<InboundLine, Integer> {
}

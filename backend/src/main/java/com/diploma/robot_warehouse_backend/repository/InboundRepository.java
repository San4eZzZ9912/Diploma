package com.diploma.robot_warehouse_backend.repository;

import com.diploma.robot_warehouse_backend.entity.Inbound;
import org.springframework.data.jpa.repository.JpaRepository;

public interface InboundRepository extends JpaRepository<Inbound, Integer> {
    boolean existsByExternalRef(String externalRef);
}

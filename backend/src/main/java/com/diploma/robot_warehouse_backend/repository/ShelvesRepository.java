package com.diploma.robot_warehouse_backend.repository;

import com.diploma.robot_warehouse_backend.entity.Shelf;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface ShelvesRepository extends JpaRepository<Shelf, Integer> {
}

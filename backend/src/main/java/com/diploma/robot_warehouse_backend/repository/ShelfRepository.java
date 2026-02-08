package com.diploma.robot_warehouse_backend.repository;

import com.diploma.robot_warehouse_backend.entity.Shelf;
import com.diploma.robot_warehouse_backend.enums.Role;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface ShelfRepository extends JpaRepository<Shelf, Integer> {
    Optional<Shelf> findFirstByRole(Role role); // или enum ShelfRole
    Optional<Shelf> findByShelfCode(String shelfCode);

}

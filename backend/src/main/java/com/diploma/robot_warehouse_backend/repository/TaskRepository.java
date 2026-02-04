package com.diploma.robot_warehouse_backend.repository;

import com.diploma.robot_warehouse_backend.entity.Task;
import com.diploma.robot_warehouse_backend.enums.Status;
import org.hibernate.dialect.lock.OptimisticEntityLockException;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

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
}

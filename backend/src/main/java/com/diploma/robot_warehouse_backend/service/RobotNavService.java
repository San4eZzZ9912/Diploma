package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.NavPoseResponse;
import com.diploma.robot_warehouse_backend.entity.Shelf;
import com.diploma.robot_warehouse_backend.entity.Task;
import com.diploma.robot_warehouse_backend.enums.Role;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.repository.ShelfRepository;
import com.diploma.robot_warehouse_backend.repository.TaskRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Optional;

@Service
public class RobotNavService {
    private final ShelfRepository shelfRepository;
    private final TaskRepository taskRepository;

    public RobotNavService(ShelfRepository shelfRepository, TaskRepository taskRepository) {
        this.shelfRepository = shelfRepository;
        this.taskRepository = taskRepository;
    }

    @Transactional
    public NavPoseResponse getPickPose(String robotId) {
        Shelf pick = shelfRepository.findFirstByRole(Role.PICK)
                .orElseThrow(() -> new IllegalStateException("No PICK shelf found"));
        return toPose(pick);
    }

    @Transactional
    public Optional<NavPoseResponse> getPlacePose(String robotId) {
        Optional<Task> tOpt = taskRepository.findFirstByRobotIdAndStatus(robotId, Status.IN_PROGRESS);
        if (tOpt.isEmpty()) return Optional.empty();

        Task t = tOpt.get();
        String code = t.getTargetShelfCode();
        if (code == null || code.isBlank()) {
            throw new IllegalStateException("IN_PROGRESS task has no target_shelf_code: taskId=" + t.getId());
        }

        Shelf shelf = shelfRepository.findByShelfCode(code)
                .orElseThrow(() -> new IllegalStateException("Shelf not found: " + code));

        return Optional.of(toPose(shelf));
    }

    private NavPoseResponse toPose(Shelf s) {
        if (s.getMapX() == null || s.getMapY() == null || s.getMapYaw() == null) {
            throw new IllegalStateException("Shelf has null map coords: " + s.getShelfCode());
        }
        return new NavPoseResponse(s.getMapX(), s.getMapY(), s.getMapYaw());
    }
}


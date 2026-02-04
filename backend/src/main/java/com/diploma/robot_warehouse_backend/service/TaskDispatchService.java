package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.TaskResponse;
import com.diploma.robot_warehouse_backend.entity.*;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.repository.SlotStateRepository;
import com.diploma.robot_warehouse_backend.repository.TaskRepository;
import jakarta.transaction.Transactional;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Optional;

@Service
public class TaskDispatchService {
    private final TaskRepository taskRepository;
    private final SlotStateRepository slotStateRepository;

    public TaskDispatchService(TaskRepository taskRepository, SlotStateRepository slotStateRepository) {
        this.taskRepository = taskRepository;
        this.slotStateRepository = slotStateRepository;
    }

    @Transactional
    public Optional<TaskResponse> getNextTask(String robotId) {
        Task task = taskRepository.findNextNewForUpdate().orElse(null);

        if (task == null) {
            return Optional.empty();
        }

        SlotState freeState = slotStateRepository.findFirstFreeForUpdate().orElse(null);

        if (freeState == null) {
            return Optional.empty();
        }

        ShelfSlot slot = freeState.getSlot();
        Shelf shelf = slot.getShelf();

        freeState.setReserved(true);
        freeState.setReservedTaskId(task.getId());
        freeState.setUpdatedAt(LocalDateTime.now());

        task.setStatus(Status.IN_PROGRESS);
        task.setRobotId(robotId);
        task.setTargetShelfCode(shelf.getShelfCode());
        task.setTargetLevel(slot.getLevel().name());
        task.setTargetSide(slot.getSide().name());
        task.setUpdatedAt(LocalDateTime.now());

        Product product = new Product();

        TaskResponse taskResponse = new TaskResponse(
                task.getId(),
                product.getSku(),
                product.getManufacturer(),
                task.getTargetShelfCode(),
                task.getTargetLevel(),
                task.getTargetSide(),
                shelf.getMapX(),
                shelf.getMapY(),
                shelf.getMapYaw()
        );

        return Optional.of(taskResponse);
    }

    @Transactional
    public void completeTask(Integer taskId, String robotId, boolean success, String observedSku, String observedManufacturer) {
        Task task = taskRepository.findById(taskId).orElseThrow(
                () -> new IllegalArgumentException("Task not found: " + taskId));

        if (!Status.IN_PROGRESS.equals(task.getStatus())) {
            throw new IllegalStateException("Task is not IN_PROGRESS: " + taskId + ", status=" + task.getStatus());
        }
        if (task.getRobotId() != null && !task.getRobotId().equals(robotId)) {
            throw new IllegalStateException("Task is owned by another robot: taskRobot=" + task.getRobotId() + ", robotId=" + robotId);
        }

        task.setObservedSku(observedSku);
        task.setObservedManufacturer(observedManufacturer);
        task.setUpdatedAt(LocalDateTime.now());

        SlotState slotState = slotStateRepository.findByReservedTaskId(taskId).orElseThrow(
                () -> new IllegalArgumentException("No reserved slot_state for taskId=" + taskId));

        slotState.setReserved(false);
        slotState.setReservedTaskId(null);

        if (success) {
            String cubeQr = buildCubeQr(observedSku, observedManufacturer);

            slotState.setOccupied(true);
            slotState.setCubeQr(cubeQr);
            slotState.setRobotId(robotId);
            slotState.setUpdatedAt(LocalDateTime.now());
            task.setStatus(Status.DONE);
        } else {
            slotState.setOccupied(false);
            slotState.setCubeQr(null);
            slotState.setRobotId(robotId);
            slotState.setUpdatedAt(LocalDateTime.now());

            task.setStatus(Status.ERROR);
        }

        slotStateRepository.save(slotState);
        taskRepository.save(task);
    }

    private String buildCubeQr(String sku, String manufacturer) {
        if (sku == null || manufacturer == null) {
            // если робот не смог прочитать QR, можно хранить null
            return null;
        }
        return sku.trim() + "/" + manufacturer.trim();
    }

}

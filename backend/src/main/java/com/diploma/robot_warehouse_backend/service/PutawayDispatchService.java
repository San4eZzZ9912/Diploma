package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.PutawayTaskResponse;
import com.diploma.robot_warehouse_backend.entity.*;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.enums.Type;
import com.diploma.robot_warehouse_backend.repository.SlotStateRepository;
import com.diploma.robot_warehouse_backend.repository.TaskRepository;
import jakarta.transaction.Transactional;
import org.springframework.stereotype.Service;
import java.time.LocalDateTime;
import java.util.Optional;

@Service
public class PutawayDispatchService {
    private final TaskRepository taskRepository;
    private final SlotStateRepository slotStateRepository;

    public PutawayDispatchService(TaskRepository taskRepository, SlotStateRepository slotStateRepository) {
        this.taskRepository = taskRepository;
        this.slotStateRepository = slotStateRepository;
    }

    @Transactional
    public Optional<PutawayTaskResponse> getNextTask(String robotId) {
        Task task = taskRepository.findNextNewPutawayForUpdate().orElse(null);

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

        task.setType(Type.PUTAWAY);
        task.setStatus(Status.IN_PROGRESS);
        task.setRobotId(robotId);
        task.setTargetSlot(slot);
        task.setUpdatedAt(LocalDateTime.now());

        Product product = task.getProduct();

        PutawayTaskResponse putawayTaskResponse = new PutawayTaskResponse(
                task.getId(),
                task.getType(),
                product.getSku(),
                product.getManufacturer(),
                shelf.getShelfCode(),
                slot.getLevel(),
                slot.getSide(),
                slot.getApriltagId(),
                shelf.getMapX(),
                shelf.getMapY(),
                shelf.getMapYaw()
        );
        slotStateRepository.save(freeState);
        taskRepository.save(task);

        return Optional.of(putawayTaskResponse);
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
            slotState.setStoredAt(LocalDateTime.now());
            slotState.setProduct(task.getProduct());
            task.setStatus(Status.DONE);
        } else {
            slotState.setOccupied(false);
            slotState.setCubeQr(null);
            slotState.setRobotId(robotId);
            slotState.setUpdatedAt(LocalDateTime.now());
            slotState.setStoredAt(null);
            slotState.setProduct(null);
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

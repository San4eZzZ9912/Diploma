package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.PutawayTaskResponse;
import com.diploma.robot_warehouse_backend.entity.Product;
import com.diploma.robot_warehouse_backend.entity.Shelf;
import com.diploma.robot_warehouse_backend.entity.ShelfSlot;
import com.diploma.robot_warehouse_backend.entity.SlotState;
import com.diploma.robot_warehouse_backend.entity.Task;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.mapper.PutawayTaskMapper;
import com.diploma.robot_warehouse_backend.repository.SlotStateRepository;
import com.diploma.robot_warehouse_backend.repository.TaskRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDateTime;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class PutawayDispatchServiceTest {

    @Mock
    private TaskRepository taskRepository;

    @Mock
    private SlotStateRepository slotStateRepository;

    @Mock
    private PutawayTaskMapper putawayTaskMapper;

    @InjectMocks
    private PutawayDispatchService putawayDispatchService;

    @Test
    @DisplayName("getNextTask: должен зарезервировать свободный слот, перевести задачу в IN_PROGRESS и вернуть response")
    void getNextTask_shouldReserveSlotAndReturnResponse() {
        String robotId = "robot-1";

        Product product = product(100);
        Task task = task(1, Status.NEW, product, null, null);

        Shelf shelf = shelf(5);
        ShelfSlot targetSlot = slot(20, shelf);

        SlotState freeState = slotState(targetSlot, false, false, null, null, null);

        PutawayTaskResponse response = mock(PutawayTaskResponse.class);

        when(taskRepository.findNextNewPutawayForUpdate()).thenReturn(Optional.of(task));
        when(slotStateRepository.findFirstFreeForUpdate()).thenReturn(Optional.of(freeState));
        when(putawayTaskMapper.toResponse(task)).thenReturn(response);

        when(slotStateRepository.save(any(SlotState.class))).thenAnswer(inv -> inv.getArgument(0));
        when(taskRepository.save(any(Task.class))).thenAnswer(inv -> inv.getArgument(0));

        Optional<PutawayTaskResponse> result = putawayDispatchService.getNextTask(robotId);

        assertTrue(result.isPresent());
        assertSame(response, result.get());

        assertTrue((Boolean) getField(freeState, "reserved"));
        assertEquals(Integer.valueOf(1), getField(freeState, "reservedTaskId"));
        assertNotNull(getField(freeState, "updatedAt"));

        assertEquals(Status.IN_PROGRESS, getField(task, "status"));
        assertEquals(robotId, getField(task, "robotId"));
        assertSame(targetSlot, getField(task, "targetSlot"));
        assertNotNull(getField(task, "updatedAt"));

        verify(slotStateRepository).save(freeState);
        verify(taskRepository).save(task);
        verify(putawayTaskMapper).toResponse(task);
    }

    @Test
    @DisplayName("getNextTask: если новой задачи нет, должен вернуть Optional.empty")
    void getNextTask_shouldReturnEmptyWhenNoTask() {
        when(taskRepository.findNextNewPutawayForUpdate()).thenReturn(Optional.empty());

        Optional<PutawayTaskResponse> result = putawayDispatchService.getNextTask("robot-1");

        assertTrue(result.isEmpty());

        verify(taskRepository).findNextNewPutawayForUpdate();
        verifyNoMoreInteractions(slotStateRepository, putawayTaskMapper);
    }

    @Test
    @DisplayName("getNextTask: если свободного слота нет, должен вернуть Optional.empty")
    void getNextTask_shouldReturnEmptyWhenNoFreeSlot() {
        Product product = product(100);
        Task task = task(1, Status.NEW, product, null, null);

        when(taskRepository.findNextNewPutawayForUpdate()).thenReturn(Optional.of(task));
        when(slotStateRepository.findFirstFreeForUpdate()).thenReturn(Optional.empty());

        Optional<PutawayTaskResponse> result = putawayDispatchService.getNextTask("robot-1");

        assertTrue(result.isEmpty());

        verify(taskRepository).findNextNewPutawayForUpdate();
        verify(slotStateRepository).findFirstFreeForUpdate();
        verifyNoMoreInteractions(putawayTaskMapper);
    }

    @Test
    @DisplayName("completeTask(success=true): должен занять слот, записать cubeQr и перевести задачу в DONE")
    void completeTask_shouldMarkSlotOccupiedAndTaskDoneWhenSuccess() {
        Integer taskId = 1;
        String robotId = "robot-1";

        Product product = product(100);
        Task task = task(taskId, Status.IN_PROGRESS, product, robotId, slot(20, shelf(5)));

        SlotState slotState = slotState(
                (ShelfSlot) getField(task, "targetSlot"),
                false,
                true,
                taskId,
                null,
                null
        );

        when(taskRepository.findById(taskId)).thenReturn(Optional.of(task));
        when(slotStateRepository.findByReservedTaskId(taskId)).thenReturn(Optional.of(slotState));

        when(slotStateRepository.save(any(SlotState.class))).thenAnswer(inv -> inv.getArgument(0));
        when(taskRepository.save(any(Task.class))).thenAnswer(inv -> inv.getArgument(0));

        putawayDispatchService.completeTask(taskId, robotId, true, " SKU-1 ", " MFG-1 ");

        assertFalse((Boolean) getField(slotState, "reserved"));
        assertNull(getField(slotState, "reservedTaskId"));
        assertTrue((Boolean) getField(slotState, "occupied"));
        assertEquals("SKU-1/MFG-1", getField(slotState, "cubeQr"));
        assertSame(product, getField(slotState, "product"));
        assertEquals(robotId, getField(slotState, "robotId"));
        assertNotNull(getField(slotState, "updatedAt"));
        assertNotNull(getField(slotState, "storedAt"));

        assertEquals(" SKU-1 ", getField(task, "observedSku"));
        assertEquals(" MFG-1 ", getField(task, "observedManufacturer"));
        assertEquals(Status.DONE, getField(task, "status"));
        assertNotNull(getField(task, "updatedAt"));

        verify(slotStateRepository).save(slotState);
        verify(taskRepository).save(task);
    }

    @Test
    @DisplayName("completeTask(success=false): должен освободить слот и перевести задачу в ERROR")
    void completeTask_shouldClearSlotAndSetErrorWhenFailed() {
        Integer taskId = 1;
        String robotId = "robot-1";

        Product product = product(100);
        Task task = task(taskId, Status.IN_PROGRESS, product, robotId, slot(20, shelf(5)));

        SlotState slotState = slotState(
                (ShelfSlot) getField(task, "targetSlot"),
                true,
                true,
                taskId,
                product,
                "OLD/QR"
        );
        setField(slotState, LocalDateTime.now().minusHours(1), "storedAt");

        when(taskRepository.findById(taskId)).thenReturn(Optional.of(task));
        when(slotStateRepository.findByReservedTaskId(taskId)).thenReturn(Optional.of(slotState));

        when(slotStateRepository.save(any(SlotState.class))).thenAnswer(inv -> inv.getArgument(0));
        when(taskRepository.save(any(Task.class))).thenAnswer(inv -> inv.getArgument(0));

        putawayDispatchService.completeTask(taskId, robotId, false, "SKU-1", "MFG-1");

        assertFalse((Boolean) getField(slotState, "reserved"));
        assertNull(getField(slotState, "reservedTaskId"));
        assertFalse((Boolean) getField(slotState, "occupied"));
        assertNull(getField(slotState, "cubeQr"));
        assertNull(getField(slotState, "product"));
        assertNull(getField(slotState, "storedAt"));
        assertEquals(robotId, getField(slotState, "robotId"));
        assertNotNull(getField(slotState, "updatedAt"));

        assertEquals("SKU-1", getField(task, "observedSku"));
        assertEquals("MFG-1", getField(task, "observedManufacturer"));
        assertEquals(Status.ERROR, getField(task, "status"));
        assertNotNull(getField(task, "updatedAt"));

        verify(slotStateRepository).save(slotState);
        verify(taskRepository).save(task);
    }

    @Test
    @DisplayName("completeTask: если задача не IN_PROGRESS, должен выбросить исключение")
    void completeTask_shouldThrowWhenTaskNotInProgress() {
        Integer taskId = 1;

        Task task = task(taskId, Status.NEW, product(100), "robot-1", slot(20, shelf(5)));

        when(taskRepository.findById(taskId)).thenReturn(Optional.of(task));

        IllegalStateException ex = assertThrows(
                IllegalStateException.class,
                () -> putawayDispatchService.completeTask(taskId, "robot-1", true, "SKU", "MFG")
        );

        assertTrue(ex.getMessage().contains("Task is not IN_PROGRESS"));

        verify(taskRepository).findById(taskId);
        verifyNoInteractions(slotStateRepository);
    }

    @Test
    @DisplayName("completeTask: если задачу завершает другой робот, должен выбросить исключение")
    void completeTask_shouldThrowWhenTaskOwnedByAnotherRobot() {
        Integer taskId = 1;

        Task task = task(taskId, Status.IN_PROGRESS, product(100), "robot-2", slot(20, shelf(5)));

        when(taskRepository.findById(taskId)).thenReturn(Optional.of(task));

        IllegalStateException ex = assertThrows(
                IllegalStateException.class,
                () -> putawayDispatchService.completeTask(taskId, "robot-1", true, "SKU", "MFG")
        );

        assertTrue(ex.getMessage().contains("owned by another robot"));

        verify(taskRepository).findById(taskId);
        verifyNoInteractions(slotStateRepository);
    }

    @Test
    @DisplayName("completeTask: если по taskId не найден зарезервированный слот, должен выбросить исключение")
    void completeTask_shouldThrowWhenReservedSlotNotFound() {
        Integer taskId = 1;

        Task task = task(taskId, Status.IN_PROGRESS, product(100), "robot-1", slot(20, shelf(5)));

        when(taskRepository.findById(taskId)).thenReturn(Optional.of(task));
        when(slotStateRepository.findByReservedTaskId(taskId)).thenReturn(Optional.empty());

        IllegalArgumentException ex = assertThrows(
                IllegalArgumentException.class,
                () -> putawayDispatchService.completeTask(taskId, "robot-1", true, "SKU", "MFG")
        );

        assertTrue(ex.getMessage().contains("No reserved slot_state"));

        verify(taskRepository).findById(taskId);
        verify(slotStateRepository).findByReservedTaskId(taskId);
    }

    // ---------------- helpers ----------------

    private Product product(Integer id) {
        Product product = new Product();
        setField(product, id, "id", "productId");
        setField(product, "SKU-" + id, "sku");
        setField(product, "MFG-" + id, "manufacturer");
        setField(product, "Product-" + id, "name");
        return product;
    }

    private Shelf shelf(Integer id) {
        Shelf shelf = new Shelf();
        setField(shelf, id, "id", "shelfId");
        setField(shelf, "SHELF-" + id, "shelfCode");
        return shelf;
    }

    private ShelfSlot slot(Integer id, Shelf shelf) {
        ShelfSlot slot = new ShelfSlot();
        setField(slot, id, "id", "slotId");
        setField(slot, shelf, "shelf");
        setField(slot, true, "enabled");
        return slot;
    }

    private SlotState slotState(
            ShelfSlot slot,
            boolean occupied,
            boolean reserved,
            Integer reservedTaskId,
            Product product,
            String cubeQr
    ) {
        SlotState state = new SlotState();
        Integer slotId = getField(slot, "id", "slotId");

        setField(state, slotId, "id", "slotId");
        setField(state, slot, "slot");
        setField(state, occupied, "occupied");
        setField(state, reserved, "reserved");
        setField(state, reservedTaskId, "reservedTaskId");
        setField(state, product, "product");
        setField(state, cubeQr, "cubeQr");
        setField(state, null, "storedAt");
        setField(state, null, "robotId");
        setField(state, null, "updatedAt");

        return state;
    }

    private Task task(
            Integer id,
            Status status,
            Product product,
            String robotId,
            ShelfSlot targetSlot
    ) {
        Task task = new Task();
        setField(task, id, "id", "taskId");
        setField(task, status, "status");
        setField(task, product, "product");
        setField(task, robotId, "robotId");
        setField(task, targetSlot, "targetSlot");
        setField(task, null, "updatedAt");
        setField(task, null, "observedSku");
        setField(task, null, "observedManufacturer");
        return task;
    }

    @SuppressWarnings("unchecked")
    private static <T> T getField(Object target, String... fieldNames) {
        for (String fieldName : fieldNames) {
            try {
                return (T) ReflectionTestUtils.getField(target, fieldName);
            } catch (IllegalArgumentException ignored) {
            }
        }
        throw new IllegalArgumentException("Field not found in " + target.getClass().getSimpleName());
    }

    private static void setField(Object target, Object value, String... fieldNames) {
        for (String fieldName : fieldNames) {
            try {
                ReflectionTestUtils.setField(target, fieldName, value);
                return;
            } catch (IllegalArgumentException ignored) {
            }
        }
        throw new IllegalArgumentException("Field not found in " + target.getClass().getSimpleName());
    }
}